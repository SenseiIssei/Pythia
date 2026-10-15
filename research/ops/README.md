# Operations on the VPS

Everything Pythia runs on the lab machine, and when. All times UTC.

| When | What | Where |
|---|---|---|
| always | market data recorder | container `pythia-recorder` (`research/recorder`) |
| always | headless engine: lab book, volatility model in shadow mode, `/api/lab` | container `pythia-server` on 127.0.0.1:8787 only |
| always | a second engine for autopilots, kept apart so they never touch the lab book's markets or evidence; state in `/srv/pythia-data/autopilot` | container `pythia-autopilot` on 127.0.0.1:8788 only |
| 03:30 | history backfill: 20 lab coins, every USDT pair, every USDT perp | `/etc/cron.d/pythia-backfill` |
| 04:00 | momentum paper books, engine signals, paper vs backtest review | `/etc/cron.d/pythia-paper` |
| 04:15 | sweep candidates as paper books: survivorship-free momentum (daily, and in seven weekly tranches), Donchian breakout (about 10 minutes, rebuilds the daily panel into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-families` |
| 04:45 | M4 shadow paper book, market-neutral on perps (`lab.paper.m4_ls`, 2 to 3 minutes, about 3 GB; rebuilds the xs_daily panel and retrains weekly into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-m4` |
| 05:30 | market-neutral M2 paper books (v1 and v2) | `/etc/cron.d/pythia-paper-ls` |
| 06:15 | forward report: every paper book and autopilot against its backtest (`lab.paper.forward_report`, seconds) | `/etc/cron.d/pythia-forward` |
| 06:30 | learning loop: demo-fill costs, forward evidence, monthly sweep refresh, weekly vol and monthly M2 retrain as challengers, nightly digest (`lab.ops.learn`, seconds; up to a few hours when a retrain is due) | `/etc/cron.d/pythia-learn` |
| 07:15 | model zoo: retrains the zoo models that are due, promotes a challenger only if better out of sample, shadow forecasts and scores, drift, the Models page report; posts promotions and drift (`lab.models.train --due`, about 5 minutes; longer on Sundays when M8, M8q and M10 retrain) | `/etc/cron.d/pythia-models` |
| 07:05 | Pokemon cards: price snapshot (`lab.collect.pokemon`, 15 to 45 minutes keyless, the API is slow and retried), then studies, fair value, forecasts, the paper collection and card alerts (`lab.pokemon.daily`, seconds at first, up to about 20 minutes with a year of history). Data and play money only | `/etc/cron.d/pythia-pokemon` |
| Sun 05:40 | cost calibration from the recorded books, report only | `/etc/cron.d/pythia-costs` |
| 05:00 | strategy factory, forward shadow step: appends the new days to each shadow book, decides those with 30 days (`lab.factory shadow`, seconds) | `/etc/cron.d/pythia-factory` |
| Sun 07:30 | strategy factory, weekly run: 300 new genomes in sample, six held-back checks, shadow review, report and digest (`lab.factory`, about a minute) | `/etc/cron.d/pythia-factory` |
| after the learning loop | daily digest to the operator's webhook (`lab.ops.notify`, seconds) | `/etc/cron.d/pythia-learn` |
| hourly :12 | CS2 skins: Skinport snapshots and sales history, Steam prices for the watchlist, then models (refit daily), alerts, the play-money portfolio (weekly) and the board for the app (`lab.collect.cs2`, then `lab.cs2.run`; 2 Skinport requests and up to 100 Steam requests, about 6 minutes) | `/etc/cron.d/pythia-cs2` |
| every 15 min | trending watcher: DexScreener boosted tokens, Binance gainers and volume surges, surge alerts on coins Alpaca lists, a daily on-chain hype digest from 08:00 (`lab.ops.trending`, seconds; reads only) | `/etc/cron.d/pythia-trending` |
| hourly :07 | health check of all of the above; posts when not ok two runs in a row | `/etc/cron.d/pythia-health` |
| every 10 minutes | listings watcher: new pairs on Alpaca, Binance, Coinbase, Kraken and Binance listing announcements, posted to Telegram (`lab.ops.listings`, seconds); then the listings paper book, off unless the W6 rule passed (`lab.paper.listings_book`) | `/etc/cron.d/pythia-listings` |

Since W14 the schedules above live in one table, `research/ops/jobs.yaml`,
and `/etc/cron.d/pythia-jobs` is rendered from it. The hand-written cron
files named in the right column, and the cron lines quoted in the sections
below, are what each job replaced; the table's `command` is the same command.

## Bootstrap a fresh server

One command, as root, on a Linux server with internet access:

```bash
git clone https://github.com/SenseiIssei/Pythia.git /opt/pythia-src && /opt/pythia-src/research/ops/bootstrap.sh
```

It installs what is missing (docker, rsync, python3, flock, curl), creates
`/srv/pythia-data`, `/srv/pythia-backup`, `/var/log/pythia` and `/etc/pythia`
(root only, with an empty `alerts.env`), builds the images `pythia-lab`,
`pythia-recorder` and `pythia-server`, deploys the lab code and the ops tools,
renders the cron file, starts the recorder and the two engines (an existing
container is never replaced) and runs the health check once. Then fill in
`/etc/pythia/alerts.env` (see "Alerts and the daily digest") and, for the
listings watcher, `/etc/pythia/alpaca-paper.env`. Running it again is safe;
`--no-install`, `--no-build` and `--no-engines` leave those steps out.

Update after a pull: `cd /opt/pythia-src && git pull && research/ops/bootstrap.sh --no-install --no-engines`,
or only the part that changed:

```bash
research/ops/deploy_lab.sh     # the lab code in /opt/pythia-lab
research/ops/deploy_ops.sh     # jobs.py, jobs.yaml, notify.py, system_health.sh in /opt/pythia-ops, then render
```

## The job table

`research/ops/jobs.yaml` lists every scheduled job once: name, schedule
(UTC cron) or `depends_on` alone (runs right after its dependencies
succeed), command (in the `pythia-lab` image with the lab code at `/app`,
another image, or on the host), resources, timeout, lock, dependencies,
`enabled`. The header of the file explains each field. `lab.ops.jobs`
(installed as `/opt/pythia-ops/jobs.py`, standard library only, so the host's
`python3` runs it) does the rest:

| Command | What |
|---|---|
| `jobs.py validate` | checks the table and lists the jobs |
| `jobs.py render [--dry-run] [--prune-legacy]` | writes `/etc/cron.d/pythia-jobs` |
| `jobs.py run <job> [--force]` | runs one job the way cron does (`--force` runs a disabled one and skips the dependency check) |
| `jobs.py status [--write]` | last run, next run, failures of every job, as JSON |
| `jobs.py checks` | the health check's rows: every job, the disk, every dataset |
| `jobs.py disk [--now]` | size and growth per dataset |
| `jobs.py prune [--dry-run]` | the retention rules |
| `jobs.py backup [--dry-run]` | archive the important state, rotate |

Every cron line runs `jobs.py run <job>`, which wraps the job the same way
each time:

- **Lock.** An exclusive `flock` on `/run/lock/pythia/<lock>.lock` (the same
  kernel lock `flock(1)` takes; it goes with the process, so a killed run
  never leaves a stale lock). A run whose lock is busy waits up to
  `lock_wait`, then is recorded as skipped. The heavy nightly jobs share the
  lock `heavy`, so two of them never compete for memory.
- **Dependencies.** A job with `depends_on` runs only when each dependency
  succeeded within `depends_within` (20 h) and is not running; otherwise the
  run is recorded as blocked and the job turns red.
- **Timeout.** Past `timeout` the container is `docker kill`ed and the
  process group stopped; the run is recorded as `timeout` (exit 124).
- **Log.** Output goes to `/var/log/pythia/<job>.log`, rotated by size
  (`log_max_mb`, `log_keep` in the table).
- **Run record.** One JSON line per run in the data lake,
  `/srv/pythia-data/_ops/runs/<YYYY-MM>.jsonl` (job, start, end, duration,
  exit code, status, reason), read with
  `pl.read_ndjson("/srv/pythia-data/_ops/runs/*.jsonl")`.
- **Status.** `/srv/pythia-data/_health/jobs.json` is rewritten after every
  run: each job's state (ok, running, never, disabled, legacy, failed,
  timeout, late, blocked, stuck), last run, last success, next run and
  failure streak. The engine serves it in `/api/lab` (`jobs`) and the Lab page
  shows it as "Scheduled jobs".
- **Alert.** A job's first failure, and its recovery, posts one line through
  `notify.py` with the settings in `/etc/pythia/alerts.env` (`alert: false`
  turns it off for a job).

A job is **late** when its last scheduled fire is past its timeout plus
`grace` (15 minutes) and no run started for it; fires before the job went
live in the rendered file do not count.

**Switching from the hand-written cron files.** Each job names the file it
replaces (`replaces: pythia-learn`). While that file is still in
`/etc/cron.d`, the job stays commented out in the rendered file (state
`legacy`), so nothing ever runs twice. Compare first, then hand over:

```bash
research/ops/deploy_ops.sh                     # installs and renders; the replaced jobs are held
python3 /opt/pythia-ops/jobs.py render --dry-run
cat /etc/cron.d/pythia-*                       # the old lines, to compare with jobs.yaml
research/ops/deploy_ops.sh --prune-legacy      # moves them to /etc/pythia/cron-legacy/, the table takes over
```

To undo, move a file back from `/etc/pythia/cron-legacy/` and render again.

**Adding a job** (a new collector, a study): add an entry to `jobs.yaml`,
`research/ops/deploy_ops.sh`, done. Its log, lock, run record, status row,
health row and alert come with it. Try it first with
`python3 /opt/pythia-ops/jobs.py run <job> --force`. Jobs whose module is not
deployed yet are in the table with `enabled: false`.

## Data growth and retention

The `datasets` section of the table names each folder of the data lake. The
health check measures them (at most every 6 hours, `_ops/disk/history.jsonl`)
and turns red when free space is under `min_free_gb`, when the disk would be
full within 14 days at the last week's growth, or when a dataset is over its
`max_gb`. A dataset with `retention_days` loses files older than that (by
modification time, only names matching its `pattern`, never through a
symlink) in the nightly `prune` job; the others are never deleted from. See
it first: `python3 /opt/pythia-ops/jobs.py prune --dry-run`.

## Backup

The nightly `backup` job archives the state that cannot be rebuilt from
market data (both engines' state files, the model registry and published
models, the paper books and the CS2 play-money portfolio, engine signals,
the learning loop's ledgers, the learned costs, the factory's trial ledger,
the forward evidence) into `/srv/pythia-backup/pythia-state-<UTC time>.tar.gz`,
mode 600, with a `.sha256` and a `.json` manifest. Each archive is read back
before it is kept. It keeps the newest of each of the last 7 days and of each
of the last 4 weeks (`keep_daily`, `keep_weekly`). The list is `backup.include`
in the table.

The archives are on the same disk as the data: copy them off the server too,
for example by adding `/srv/pythia-backup` to the PC sync. Restore one:

```bash
sha256sum -c /srv/pythia-backup/pythia-state-<time>.tar.gz.sha256
docker stop pythia-server pythia-autopilot
tar -xzf /srv/pythia-backup/pythia-state-<time>.tar.gz -C /srv/pythia-data
docker start pythia-server pythia-autopilot
```

## Deploying the lab code

`research/ops/deploy_lab.sh` copies `research/lab` to `/opt/pythia-lab`
(the folder the lab image mounts at `/app`). It refuses while a job
container runs, so no job sees half old, half new code (`--force` overrides). The code is synced with
`--delete`; `results/` and every cache are excluded from that, so what the
studies wrote on the server is never overwritten or deleted. New files under
the repo's `results/` (a seed such as `results/factory_seed`, a new study's
write-up) are added only where the server has none. Afterwards every deployed
file is checked against a sha256 manifest (`.deploy-manifest`) and every file
`results/` had before must still be there unchanged; otherwise the script
fails. `.deploy-info` says which commit is deployed. `--dry-run` shows what
would change. Rebuild the image only when `research/lab/requirements.txt`
changed: `docker build -t pythia-lab /opt/pythia-lab`.

## Health check

`system_health.sh` looks at the containers, the recorder's streams, every job
of the table (late, failing, blocked or stuck jobs go red, through
`jobs.py checks`), the disk and every dataset's size and growth, each paper
book's last row, the model service and the engine's market data
(`dataHealth` in `/api/state`), and writes
`/srv/pythia-data/_health/system.json`. It never restarts anything. The Lab
page shows it ("Is everything running?"); the PC gets it with the sync. Red
for two runs in a row posts once to Telegram (below, "Health alarm").

It runs as the job `health` of the table. Install or update with
`research/ops/deploy_ops.sh` on the server.

## Forward report

`lab.paper.forward_report` reads the paper journals and the autopilot
engine's `/api/state` and writes `/srv/pythia-data/reports/forward/`
(`latest.json`, `latest.md`, dated copies). Both engines mount the reports
read-only, so the Lab page of either shows it as "Forward test". The
container needs the host network to reach the autopilot engine on
127.0.0.1:8788; if the engine is down the report says so and still covers the
paper books. `/etc/cron.d/pythia-forward`:

```cron
# Pythia: daily forward report, paper books and autopilots against their backtests. Reads only.
15 6 * * * root docker run --rm --network host --memory 2g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.paper.forward_report >> /var/log/pythia-forward.log 2>&1
```

The bands come from the backtests' out-of-sample daily returns in
`reports/forward/backtest/<book>.json`. The momentum books can be exported on
the VPS itself; the sweep candidates and M4 need the sweep's run caches and
the xs_daily pick cache (the tranche book is re-simulated on the sweep's cached
panel), which live where those experiments ran, so their files are exported
there and copied over:

```bash
docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.paper.forward_report --export-backtests
scp <exported>/forward/backtest/*.json pythia-vps:/srv/pythia-data/reports/forward/backtest/
```

Re-export after an experiment is re-run. Books without a file fall back to an
approximate band from their report (growth and volatility), marked as such.

## Strategy factory

`lab.factory` (see "Strategy factory" in `research/lab/README.md`) searches a
fixed budget of new long-only strategies on the in-sample window, counts each
one in `/srv/pythia-data/factory/ledger.jsonl` (a ledger that only grows, on
top of the 377 hand-study trials), sends six a week to the held-back window,
and runs the survivors 30 days as forward shadow books before anything can
become a paper book. It reads the daily panel the paper-families job caches in
`/srv/pythia-data/lab-cache`, so it runs after 04:15. It writes only
`/srv/pythia-data/factory/` and `/srv/pythia-data/reports/factory/`; a
promoted genome is listed in `factory/promoted.json`, which the paper-families
job steps as one more paper book. It has no way to reach the engines, live
settings or money. With `--notify` the weekly digest (what was tried, what
survived the held-back window and why, the shadow books) goes to the webhook or
Telegram chat in `/etc/pythia/alerts.env`; the daily step posts only when a
shadow book is decided.

The first run was made on the PC; its trials and its shadow book are in
`research/lab/results/factory_seed/`, which every run merges into
`/srv/pythia-data/factory/` first (only what is missing). `/opt/pythia-lab`
must carry that folder, as it carries the rest of `research/lab`.

`/etc/cron.d/pythia-factory`:

```cron
# Pythia: strategy factory. Daily forward shadow step, weekly search and held-back checks with a digest. Paper only; never touches live settings or money.
0 5 * * * root docker run --rm --memory 2g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.factory shadow --notify >> /var/log/pythia-factory.log 2>&1
30 7 * * 0 root docker run --rm --cpus 4 --memory 4g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.factory --notify >> /var/log/pythia-factory.log 2>&1
```

A larger or smaller week: `--budget N`. See the last digest without posting:

```bash
docker run --rm -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.factory digest --dry-run
```

## Learning loop

`lab.ops.learn` runs every night after the forward report and keeps the
system improving on its own, inside fixed bounds. Each step is isolated; a
failing one is named in the digest and the rest still run.

| Step | When | What it does | Writes |
|---|---|---|---|
| costs | nightly | reads the autopilot engine's orders (`GET /api/state`, or `PYTHIA_LEARN_ORDERS_FILE`), keeps the finished demo orders of the Alpaca paper account in a ledger that only grows, measures per symbol realised against modelled and base-table slippage and the maker (limit) and taker (market) fill rates. A symbol's `halfSpreadBps` and `impactCoeff` are scaled by realised over base cost only from 30 market fills on, by at most 4x and inside fixed bounds; fees, borrow, minimum notional and depth never move | `learn/fills.jsonl`, `costs/learned.json` (base table plus a `measured` section) |
| evidence | nightly | snapshots `reports/forward/evidence.json` and tracks, per paper book and autopilot, its status, since when, the one before and how often it was ok in the last 30 reports | `learn/evidence_history.jsonl`, `reports/learn/evidence.json` |
| sweep | every 28 days | re-runs the strategy-family sweep on fresh data in `learn/sweep/<date>`; publishes its reports and run caches to `PYTHIA_AGENT_OUT` only if every pick is there with finite numbers and no fewer variants are counted (the old files are kept in `models/registry/families_sweep/previous/`); lists every gate that flipped. A pick that newly passes is flagged for the owner's review | `reports/learn/gates.json` |
| vol | Sundays | retrains the volatility model as a challenger (`lab.experiments.vol --challenger`) | `models/registry/vol_1h/` |
| m2 | every 28 days | retrains M2 v2 as a challenger (`lab.experiments.picks --perp-features --challenger`) | `models/registry/picks_7d/` |
| digest | nightly | what changed, what was promoted or rejected and why, each autopilot's P&L today and since start against BTC over the same windows | `reports/learn/latest.md`, `latest.json`, dated copies |

**Champion and challenger.** A challenger first has to pass its own gate (the
volatility model: better than HAR, significant, not worse in the last four
quarters; M2: walk-forward rank-IC positive with t of at least 2). Then both
are scored on the rows the champion never saw (after its training end plus the
label horizon): the champion with its own model file, the challenger with the
walk-forward predictions behind its out-of-sample numbers. It replaces the
champion only if it wins by a margin (1 % lower QLIKE, 0.005 higher rank-IC) on
a window of at least 7 days (vol) or 14 days (M2); otherwise the champion
stays. A promotion is copied to `models/<name>/<version>/`, a name that sorts
after the running one, so the engine switches to it on its next hourly check.
Every decision, promoted or not, is a line in
`models/registry/<name>/decisions.jsonl`; `champion.json` says which version is
in force and since when. Without a champion, a challenger that passes its gate
is promoted.

**What it can never do** (`lab/ops/guard.py`, tested): write anywhere but its
own folders, the learned cost file, the model registry and the published model
folders (never the engine's state, settings, keys or the paper books); call the
engine for anything but `GET /api/state`; change a fee, a venue default or a
symbol the base table does not list. Live settings, arming live, moving money
and risk limits live in the engine's state and settings, which the loop only
reads, so it cannot change them. The engine's own auto pick keeps reading the
forward report's `evidence.json` as before.

Install once: the base cost table the loop scales from (copy again whenever
`config/costs.json` changes in the repo), then the cron line. The weekly
retrain moves into the loop, so its old cron line goes.

```bash
install -D -m 644 config/costs.json /srv/pythia-data/costs/base.json
```

```bash
rm -f /etc/cron.d/pythia-retrain
```

`/etc/cron.d/pythia-learn` (host network to read the autopilot engine on
127.0.0.1:8788; `PYTHIA_AGENT_OUT` the same folder the paper-families job uses):

```cron
# Pythia: nightly learning loop. Updates evidence, costs and models within fixed bounds; never touches live settings or money.
30 6 * * * root docker run --rm --network host --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.ops.learn >> /var/log/pythia-learn.log 2>&1
```

Run a step now, or leave the heavy ones out:

```bash
docker run --rm --network host --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.ops.learn --force vol
```

```bash
docker run --rm --network host --memory 2g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.learn --no-train
```

Both engines already mount the reports read-only, so the Lab page of either
shows the digest as "What the system learned last night". The learned costs
are used only if the operator opts in: add
`-e PYTHIA_COSTS_FILE=/data/costs/learned.json -v /srv/pythia-data/costs:/data/costs:ro`
to the autopilot engine's `docker run` and recreate the container (the cost
file is read at start). Until a symbol has 30 demo market fills the learned
file equals the base table for it.

## Model zoo

`lab.models.train --due` is the one entry point for every model the zoo
trains itself (M8 direction, M8q return quantiles, M10 regime-aware daily
volatility, M11 slippage of the demo fills, M12 BTC and SPY correlation
regime). M1 and M2 stay with the learning loop above; the zoo only reports
on them. Each run, per model:

| Step | What it does | Writes |
|---|---|---|
| data | builds the model's panel from the recorder's history, the learning loop's fills ledger (M11, from 30 market fills) or Yahoo's daily chart (M12, cached a day) | `models/zoo/_data/` |
| retrain | when due (M8, M8q, M10 Sundays, M11 Mondays, M12 every 28 days): purged walk-forward against the model's baseline, a challenger folder, the registry's champion and challenger decision. A challenger that does not beat its baseline (gate: lower loss, Diebold-Mariano p below 0.05) is never promoted; one that does replaces the champion only if it is also better on the rows the champion never saw | `models/registry/<name>/`, `models/<name>/<version>/` |
| shadow | the champion (or, without one, the newest candidate, marked as such) writes down its forecast for the newest day before the outcome is known; forecasts whose outcome is now known are scored against the baseline | `models/zoo/<name>/shadow.jsonl` |
| drift | the last 30 days of each input against its training deciles, the engine's rules | in the report |
| report | every model with its score against its baseline over time, last retrain, drift and who uses it, with the lab feed header | `reports/models/latest.json`, `latest.md` |

A promotion, or a model whose inputs leave their trained range, is posted
once through `lab.ops.notify` (Telegram or webhook from
`/etc/pythia/alerts.env`). It writes only through `lab/ops/guard.py`: its
own folders, the registry and the zoo's published model folders. No book
reads a zoo model today; a model may be offered to one only after it passes
its gate.

`/etc/cron.d/pythia-models` (after the learning loop, which fills the M11
ledger; Yahoo needs outbound network, no engine access):

```cron
# Pythia: model zoo. Retrains what is due, promotes a challenger only if better out of sample; shadow, drift, report; posts promotions and drift.
15 7 * * * root docker run --rm --cpus 4 --memory 8g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.models.train --due >> /var/log/pythia-models.log 2>&1
```

Retrain one now, or only shadow and report:

```bash
docker run --rm --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.models.train --force m8q,m12 --no-notify
```

```bash
docker run --rm --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.models.train --status --no-notify
```

## Market data in the engine

The engine's crypto quotes, candles and books come from `pythia_core::feeds`,
with a priority list of public venues per kind:

| Kind | Sources, best first | Fails over when |
|---|---|---|
| quotes | Kraken stream, Kraken, Binance, Coinbase, Bybit, OKX | 10 s of stream silence, 25 s without a polled quote, or two failed polls |
| candles (5 min) | Kraken, Binance, Coinbase, Bybit, OKX | 150 s without a refresh, or two failed polls |
| books (top 20) | the executing exchange only (Binance also via its data mirror) | 60 s; past that fills use the calibrated costs |

A market returns to a better source once it has delivered for a minute
without a gap. A quote more than 5 % from every other venue's recent price is
refused and never becomes the mark; stops and trims wait while a price is older
than the risk limit (30 s). The health check's "market data" line is red when
quotes or candles are stale at the moment it runs. With `PYTHIA_WEBHOOK_URL`
set, the engine also posts once when data has been stale for 5 minutes and once
when it recovers.

Knobs, all optional, in the server's environment: `PYTHIA_FEED_QUOTES` and
`PYTHIA_FEED_CANDLES` (comma lists of `kraken-ws,kraken,binance,coinbase,bybit,okx`),
`PYTHIA_FEED_STREAM=0`, `PYTHIA_FEED_STALE_SEC`, `PYTHIA_FEED_RECOVER_SEC`,
`PYTHIA_FEED_MAX_DEVIATION_PCT`, `PYTHIA_FEED_ALERT_MIN`.

## Pokemon cards

Data, forecasts, a paper collection and alerts. No order of any kind: the
cards are physical and the owner trades them by hand. Sources and limits
are in the docstring of `lab/collect/pokemon.py`; results in
`research/lab/results/pokemon.md`.

`/etc/cron.d/pythia-pokemon`:

```cron
# Pythia: Pokemon card prices into the lake, then studies, forecasts, the paper collection and card alerts. Never buys or sells.
5 7 * * * root docker run --rm --cpus 2 --memory 6g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab sh -c 'python -m lab.collect.pokemon --sealed && python -m lab.pokemon.daily' >> /var/log/pythia-pokemon.log 2>&1
```

- The Pokemon TCG API works without a key (about 30 requests a minute,
  1,000 a day; a run is about 85 card pages). It is slow and has bad hours:
  a page of 250 cards takes about 10 s, and on the first real run /sets
  answered 500 and 502 for minutes and single card pages needed a minute of
  retries, so plan on 15 to 45 minutes. The collector retries a page up to 8
  times with backoff, then the whole run up to 3 times 5 minutes apart
  (`--attempts`, `--pause`), each attempt continuing from the day cache; if
  /sets never answers it rebuilds the sets from the cards. With a free key
  from https://dev.pokemontcg.io add `POKEMONTCG_API_KEY=<key>` to
  `/etc/pythia/alerts.env` (root-only); the collector then spaces requests
  0.3 s instead of 2.1 s. The key is read from the environment only.
- Cardmarket: the API stopped refreshing Cardmarket prices for most cards
  in mid 2026 (TCGplayer is daily). Blocks older than 14 days are kept but
  count for nothing; the report, the feed and the Cards page say so.
- The daily job also writes `reports/pokemon/latest.json` with the lab feed
  header (docs/LAB-FEEDS.md), so the Research page and Home insights pick
  it up with the other feeds.
- `--sealed` reads tcgcsv.com (TCGplayer's daily dump): sealed product and
  the single cards of the 24 newest groups plus every main set of the last
  two years and the next releases (about 100 requests). Keep it on: the
  Pokemon TCG API has no price for any 2026 set, so the new-set study and
  the Cards page's New sets come only from here. If it fails the card
  snapshot is still written and the meta file says so.
- Card alerts use the same Telegram bot or webhook as the digest, with
  `<prefix> cards` as the first line.
- Reprint announcements: list them by hand in
  `/srv/pythia-data/pokemon/reprints.csv` (`name,announced`, one card name
  and a YYYY-MM-DD date per line); the reprint study picks them up.
- The Cards page reads `pokemon/ui/latest.json` through the engine. Add
  `-v /srv/pythia-data/pokemon/ui:/data/pokemon/ui:ro -e PYTHIA_DATA=/data`
  to the `docker run` of the engine that serves the app and recreate it; the
  desktop app reads the synced folder as for the Lab page.
- First run by hand, to see it work:

```bash
docker run --rm --memory 6g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.collect.pokemon --max-pages 2 --dry-run
docker run --rm --memory 6g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab sh -c 'python -m lab.collect.pokemon --sealed && python -m lab.pokemon.daily --no-alerts'
```

The health check reports "pokemon cards" red when the paper collection has no
row for today after 10:00 UTC, once `/srv/pythia-data/pokemon` exists.

## Alerts and the daily digest

Everything goes to the owner's Telegram chat, one design for all of it (a
card: bold title with one emoji, a short summary, aligned numbers with green
and red circles); the full list, the look and the API are in `docs/ALERTS.md`:

- the engine's alerts, as they happen: autopilot events, the fills of an
  autopilot (a rebalance as one message with a small table), big moves of a
  held coin or an autopilot's equity, kill switch, floors, daily loss brake,
  orders refused, reconcile mismatch, market data stale, model drift
- lab posts: the factory, trending, and any job that posts a card through
  `POST /api/alerts/event` or `lab.ops.notify`
- the daily digest after the learning loop, with a chart of each autopilot's
  equity against BTC, P&L per sleeve and positions
- the weekly report on Sunday at 18:00 Europe/Berlin, with the week's chart
- the health alarm: `system.json` not ok for two runs in a row, posted once,
  and once when green again

Each category has a switch in the app (Notifications, "What is sent"), and
quiet hours (23:00 to 07:00 Europe/Berlin unless changed there) hold back all
but urgent alerts and list them in one message after.

Nothing is posted until the bot is set. Keep its token in one root-only env
file on the server, outside the repo and outside every log:

```bash
install -d -m 700 /etc/pythia
install -m 600 /dev/null /etc/pythia/alerts.env
cat > /etc/pythia/alerts.env <<'ENV'
PYTHIA_TELEGRAM_BOT_TOKEN=<token from BotFather>
PYTHIA_TELEGRAM_CHAT_ID=<your chat id>
ENV
```

The chat id: send the bot any message, then read it from the bot's
`getUpdates`. Instead of Telegram, `PYTHIA_ALERT_WEBHOOK=<webhook URL>` with
`PYTHIA_ALERT_FORMAT=discord` or `slack` posts the same cards in markdown.
Optional: `PYTHIA_ALERT_PREFIX` (the footer, default `Pythia`), and for the
engine `PYTHIA_ALERT_REJECTS` (3), `PYTHIA_ALERT_DEDUP_MIN` (30),
`PYTHIA_ALERT_MAX_PER_HOUR` (20).

**Lab image.** The charts need matplotlib, which is in
`research/lab/requirements.txt`: rebuild the image once after copying the lab
(`docker build -t pythia-lab /opt/pythia-lab`, or `research/lab` from a
checkout). Without it the digest and the report go out as text.

**Engine.** Add `--env-file /etc/pythia/alerts.env` to the `docker run` of the
engine that runs the autopilots (and of the lab engine, if its alerts are
wanted too, with a different `PYTHIA_ALERT_PREFIX` via `-e`), give it the
notify folder with `-v /srv/pythia-data/reports/notify:/data/reports/notify -e PYTHIA_DATA=/data`
(the last digest, digest requests, the settings file for the lab, event
images), and recreate the container. The log says
`operator alerts on (Telegram format)` at start. The switches, quiet hours and
big-move sizes are saved in its state file and written to
`/srv/pythia-data/reports/notify/settings.json`, which every lab job reads.

Lab jobs in their own containers reach the engine's `127.0.0.1:8788` through
Docker's port mapping, so the engine sees them from the bridge, not from
127.0.0.1: to let them post through `POST /api/alerts/event`, add
`-e PYTHIA_ALERT_EVENT_FROM=172.17.` (the bridge's prefix; `docker network
inspect bridge` shows it) to the engine. Without that, lab jobs post straight
to Telegram through `lab.ops.notify`, with the same design, switches and quiet
hours, which is the default.

**Daily digest.** It runs right after the learning loop, in the same cron
line, so it always reads tonight's report. `--network host` lets it read the
engine's state on 127.0.0.1:8788 for the chart. `/etc/cron.d/pythia-learn`
becomes:

```cron
# Pythia: nightly learning loop, then the daily digest with its chart to the owner's Telegram. Never touches live settings or money.
30 6 * * * root docker run --rm --network host --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.ops.learn >> /var/log/pythia-learn.log 2>&1; docker run --rm --network host --memory 1g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.notify >> /var/log/pythia-notify.log 2>&1
```

See it without posting:

```bash
docker run --rm --network host -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.notify --dry-run
```

**Weekly report.** Sunday from 18:00 Europe/Berlin, once a week. The cron
runs hourly on Sunday afternoons in UTC (16:05 to 21:05, which is 18:05 or
17:05 Berlin and later, summer or winter); the job sends when it is 18:00 or
later in Berlin and nothing went out this week yet. `/etc/cron.d/pythia-weekly`:

```cron
# Pythia: the weekly report with its chart, Sunday from 18:00 Europe/Berlin. Posts once a week.
5 16-21 * * 0 root docker run --rm --network host --memory 1g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.notify --weekly >> /var/log/pythia-notify.log 2>&1
```

Now, whatever the day: `... python -m lab.ops.notify --weekly --force`.

**Health alarm.** `system_health.sh` runs `/opt/pythia-ops/notify.py --health`
after each check when that file and `/etc/pythia/alerts.env` exist
(`PYTHIA_NOTIFY_PY` and `PYTHIA_ALERT_ENV` move them). It needs only
`python3` on the host. Install with the health script (and again after an
update of `notify.py`):

```bash
install -m 755 research/ops/system_health.sh /opt/pythia-ops/system_health.sh
install -m 644 research/lab/lab/ops/notify.py /opt/pythia-ops/notify.py
```

The cron line of the health check stays as it is.

**Digest on demand, and after quiet hours.** `POST /api/alerts/digest` on the
engine writes `reports/notify/request.json`; this cron line sends the digest
within five minutes, with the same `notify.py` the health alarm uses (stdlib
only, no container start, so without the chart). It also sends a daily digest
that fell into quiet hours once they are over, and one note listing the lab
posts quiet hours held back. Otherwise it does nothing.
`/etc/cron.d/pythia-notify-pending`:

```cron
# Pythia: a digest asked for through the engine API, and what quiet hours held back. Posts nothing otherwise.
*/5 * * * * root set -a; . /etc/pythia/alerts.env; PYTHIA_DATA=/srv/pythia-data python3 /opt/pythia-ops/notify.py --pending >> /var/log/pythia-notify.log 2>&1
```

**One card from a script.** `python3 /opt/pythia-ops/notify.py --event venue "Disk almost full" "12 GB left"`
(after `set -a; . /etc/pythia/alerts.env` and with `PYTHIA_DATA=/srv/pythia-data`),
in any of the categories listed in `docs/ALERTS.md`.

## CS2 skins (W8)

Market data, predictions, a play-money portfolio and alerts for the CS2 skins
market. **Nothing buys or sells**: automated trading on the Steam Community
Market or any skin marketplace breaks their terms and puts the account at
risk, so the owner trades by hand, if at all. The sources are public and need
no key: Skinport's `/v1/items` and `/v1/sales/history` (8 requests per 5
minutes allowed, the job makes 2 an hour) and Steam's `priceoverview` (one
request every 3.2 s, at most 100 a run, a 429 waits 60 s then 120 s and a
third ends the Steam part of the run; the watchlist resumes where it stopped).
After a run Steam refused outright, the next run knocks once and stops at the
first 429 without waiting (`steam_cooling` in `cs2/collector.json`).

Steam on the first real run (2026-10-15, from the PC): Skinport answered
(25,143 items, 36,470 sales rows), Steam answered every `priceoverview`
request from the collector with 429, from the first one on, while the same
URL fetched with curl from the same machine at the same time was answered.
Steam treats some clients differently; the collector does not try to look
like another client. Check `steam_ok` in `cs2/collector.json` after the
first runs on the lab machine: until it is above 0 the spread study, the gap
alerts and the Steam column stay empty, and everything else works on
Skinport alone.

The image needs `brotli` (in `requirements.txt`): rebuild it once.

```bash
docker build -t pythia-lab /opt/pythia-lab
```

`/etc/cron.d/pythia-cs2` (default bridge network: it needs the internet, not
the engines; the env file only for the Telegram alerts):

```cron
# Pythia: CS2 skins, hourly. Collects public prices, refits daily, alerts, paper portfolio. Never trades.
12 * * * * root docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.collect.cs2 >> /var/log/pythia-cs2.log 2>&1; docker run --rm --memory 4g --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.cs2.run >> /var/log/pythia-cs2.log 2>&1
```

What it writes, under `/srv/pythia-data`:

| Path | What |
|---|---|
| `cs2/skinport_items/date=*/HHMM.parquet` | every item each hour: lowest and highest ask, mean, median, listings |
| `cs2/skinport_sales/date=*/HHMM.parquet` | 24 h, 7, 30 and 90-day sales min, max, average, median, volume |
| `cs2/steam_prices/date=*/HHMM.parquet` | the watchlist (cases, popular skins, sticker capsules from `lab/collect/cs2_watchlist.json`, plus the 40 most traded Skinport items): lowest ask, median, 24 h volume |
| `cs2/daily/{skinport,steam}/date=*.parquet` | the day's last snapshot per item, what the models read |
| `cs2/model/` | today's predictions, how they were made and the research summary |
| `cs2/paper/state.json`, `journal.csv` | the play-money portfolio (10,000 EUR) |
| `cs2/alerts.jsonl`, `alerts_state.json` | alerts sent, 24 h cooldown per item and kind |
| `reports/cs2/latest.json` | hourly: the lab feed (title, status, headline, items; `docs/LAB-FEEDS.md`) for the Research page and Home, and the board for the CS2 Skins page (`rows`, `portfolio`, `alerts`, `research`) |
| `reports/cs2/<date>.json`, `latest.md` | the research report, daily (`results/cs2.md` in the repo) |
| `reports/cs2_weekly/` | the weekly paper report, at each weekly look (a feed too) |

About 1.5 MB a run (0.6 MB items, 0.9 MB sales history), so about 35 MB a
day and 13 GB a year; the models read only `cs2/daily/` (about 1.5 MB a
day), so the hourly folders can be thinned later without losing a model
input. Alerts (cross-market gaps of 5 % or more after both
venues' fees in items Steam trades 20 a day or more; liquid items 15 % under
their 30-day median and 10 % down in 24 h) and the weekly summary go to the
same Telegram chat or webhook as the digest. Drop pool changes and new
operations go into `events` in `lab/collect/cs2_watchlist.json` as they
happen, for the event study. Run once by hand, without posting:

```bash
docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.collect.cs2 --steam-max 10
docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.cs2.run --dry-run
```

The health check has a `cs2 collector` row (last run within three hours).

## Trending watcher

`lab.ops.trending` looks every 15 minutes at what the crowd is chasing and
never trades: DexScreener's top boosted tokens and latest token profiles (with
each token's most liquid pair and risk flags: thin liquidity, a pair under 3
days old, FDV over 50x liquidity, volume over 20x liquidity, few sells), the
24h tickers of every Binance USDT pair (top gainers) and, for the coins Alpaca
lists, 24h quote volume and trade count against their 28-day median.

- Every run writes one parquet file to the data lake,
  `/srv/pythia-data/trending/snapshots/date=<day>/<HHMMSS>.parquet` (one row
  per item, `kind` alpaca, gainer, market_surge or dex; read a range with
  `pl.read_parquet(".../trending/snapshots/**/*.parquet", hive_partitioning=True)`),
  and rewrites `reports/trending/latest.json` (title, updatedMs, status,
  headline, items, then the full snapshot).
- Rate limits: 3 to at most about 10 DexScreener calls (boosts, profiles,
  one pair call per chain, at most 5 search fallbacks) and 1 Binance ticker
  call per run;
  the Alpaca coins' 28-day klines are fetched once per UTC day (32 calls at
  weight 2) and cached in `trending/state.json`. Requests are spaced 250 ms
  per host, and a 429 or 418 stops calls to that host for the rest of the run.
- A strong surge on a coin Alpaca lists (volume 3x its 28-day median and up
  8 % in 24 h, or 2x and up 20 %) is posted at once, at most once per coin per
  20 hours, as "watch only".
- At the first run from 08:00 UTC a short digest goes out: the Alpaca coins'
  volume ratios, Binance's top gainers and volume surges, and the on-chain
  hype, labelled high risk and read-only. On-chain tokens are not on Alpaca;
  nothing here trades on a DEX or touches a wallet.

It posts through the same settings as the digest (`/etc/pythia/alerts.env`,
Telegram or webhook). `PYTHIA_ALPACA_COINS` (comma separated bases) overrides
the list of coins Alpaca lists. `/etc/cron.d/pythia-trending`:

```cron
# Pythia: trending watcher. Public market data only; posts surge alerts and a daily watchlist; never trades.
*/15 * * * * root docker run --rm --memory 512m --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app -e PYTHIA_AGENT_OUT=/data/lab-cache pythia-lab python -m lab.ops.trending >> /var/log/pythia-trending.log 2>&1
```

See it without posting or writing:

```bash
docker run --rm -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.trending --dry-run
```

The health check marks it red when `reports/trending/latest.json` is older
than 45 minutes.

## New listings (W6)

`lab.ops.listings` diffs the asset lists of Alpaca (only with the paper key
pair in the environment), Binance, Coinbase and Kraken, and reads Binance's
listing announcements. The first run only seeds what exists; after that every
new pair is a row in `/srv/pythia-data/listings/first_seen` (parquet, with
its first-seen time), and every new coin, every new Alpaca pair and every new
announcement goes out as its own message (venue, symbols, whether Alpaca lists
the coin, first price; at most 10 a run, a burst beyond that in one) through
the same Telegram or webhook settings as the digest (`/etc/pythia/alerts.env`,
`PYTHIA_TELEGRAM_BOT_TOKEN` and `PYTHIA_TELEGRAM_CHAT_ID`). The cockpit feed
is `reports/listings/latest.json` (title, updatedMs, status, headline, items,
plus the last 90 days of events), which the engine serves in `/api/lab` and
the Markets page shows as New listings. A venue that fails is skipped for that
run and named on the page.

Put the Alpaca paper pair (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, the same
pair as for the demo) in its own env file, readable by root only, for example
`/etc/pythia/alpaca-paper.env`; without it the watcher still runs and says
"Alpaca: unknown". `/etc/cron.d/pythia-listings`:

```cron
# Pythia: new coin listings every 10 minutes, posted to Telegram; then the listings paper book (off unless W6 passed).
*/10 * * * * root docker run --rm --memory 512m --env-file /etc/pythia/alerts.env --env-file /etc/pythia/alpaca-paper.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab sh -c 'python -m lab.ops.listings && python -m lab.paper.listings_book' >> /var/log/pythia-listings.log 2>&1
```

Try it once by hand first (prints, writes and posts nothing):

```bash
docker run --rm --env-file /etc/pythia/alpaca-paper.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.listings --dry-run
```

The study (`lab.experiments.listings`, pre-registered in
`research/lab/results/listings.md`) runs once by hand; it reads the lake's
hourly bars and the public APIs of Coinbase, Kraken and Alpaca (listing dates
are cached in `hist/listings`), about 50 minutes the first time, mostly
Coinbase's candles. It ran on 2026-10-15 on a copy of the lake: no rule
passed, so the listings paper book stays off and the watcher only alerts.
Running it again on the server is only needed to refresh the numbers:

```bash
docker run --rm --memory 4g --env-file /etc/pythia/alpaca-paper.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.experiments.listings
```

It writes the results below the marker in `results/listings.md` (copy it back
into the repo) and `reports/listing_effect/latest.json`, which turns the
listings paper book on only if the pre-registered rule passed. The engine that
serves `/api/lab` needs the listings folder if it does not mount the whole data
folder: add `-v /srv/pythia-data/reports/listings:/data/reports/listings:ro`
and `-e PYTHIA_DATA=/data` to its `docker run`.
