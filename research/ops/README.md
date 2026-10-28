# Operations on the VPS

Everything Pythia runs on the lab machine, and when. All times UTC.

| When | What | Where |
|---|---|---|
| always | market data recorder | container `pythia-recorder` (`research/recorder`) |
| always | headless engine: lab book, volatility model in shadow mode, `/api/lab` | container `pythia-server` on 127.0.0.1:8787 only |
| always | a second engine for autopilots, kept apart so they never touch the lab book's markets or evidence; state in `/srv/pythia-data/autopilot` | container `pythia-autopilot` on 127.0.0.1:8788 only |
| 00:40 | flow data: Coinbase BTC-USD 1h and Upbit KRW-BTC 1d (the exchange premiums), USD/KRW, DefiLlama stablecoin supply, Deribit BTC and ETH DVOL, a Deribit option snapshot with the 25-delta skew at 30 days (`lab.collect.flow`, under a minute daily; the first run fetches the history back to 2019 in about 4 minutes). Into `/srv/pythia-data/flow/`, read by the X6 study (`results/flow_overlays.md`) | `jobs.yaml` only |
| 00:50 | Wikipedia page views: daily user views of each mapped coin's English article and its redirects from the Wikimedia REST API (`lab.collect.wiki`, keyless, about 360 small requests at most 4 a second, a minute or two; the first run fetched the history back to 2015-07-01). Into `/srv/pythia-data/flow/wiki_pageviews.parquet` and `wiki_titles.parquet`, read by `attention_wiki` | `jobs.yaml`: `wiki-collect` |
| hourly :05, :15 and daily 00:20, 00:40, 01:20 | D2 free data, point in time (`lab.collect.pit`: every row with the time it describes, collected_us, known_us and backfilled): Deribit BTC and ETH DVOL hourly, ATM IV and 25-delta skew at 7, 30 and 90 days and put/call open interest (`lab.collect.deribit_vol`, :05); Hyperliquid funding, open interest and mark/oracle premium of the universe's coins and their funding history (`lab.collect.hyperliquid`, :15, one request every 1.5 s, the history shared over the first runs); Fear and Greed (`lab.collect.fear_greed`, 00:20); US 2y and 10y yields and VIX from FRED, dollar index, gold and VIX from Yahoo (`lab.collect.macro`, 00:40); DefiLlama stablecoin supply and its daily change, DEX volume in total and on Solana, Solana TVL (`lab.collect.defillama`, 01:20). Keyless, seconds to minutes; each first run is its backfill. Into `/srv/pythia-data/free/<source>/`, each with a `health.json` the health check reads (`feed <source>` rows) | `jobs.yaml`: `free-deribit`, `free-hyperliquid`, `free-feargreed`, `free-macro`, `free-defillama` |
| 03:30 | history backfill: 20 lab coins, every USDT pair, every USDT perp | `/etc/cron.d/pythia-backfill` |
| 04:00 | momentum paper books, engine signals, paper vs backtest review | `/etc/cron.d/pythia-paper` |
| 04:15 | sweep candidates as paper books: survivorship-free momentum (daily, and in seven weekly tranches), Donchian breakout (about 10 minutes, rebuilds the daily panel into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-families` |
| 04:30 | EXPERIMENT memecoin paper books (rotation and momentum on Alpaca's six memecoins) and their experimental engine signals (`lab.paper.memes`, a minute; daily klines from data.binance.vision, topped up from the public klines endpoint) | `jobs.yaml`: `paper-memes` |
| hourly :07 | EXPERIMENT 4h trend with pullback maker entries: the hour's fills and exits, a decision at every 4h close, the signal when the holdings change (`lab.paper.trend4h`, about 67 public kline requests) | `jobs.yaml`: `paper-trend4h` |
| every 5 min | pump.fun PAPER watcher: new Solana pools from GeckoTerminal, graduations bought on paper by three pre-registered rules, marks from DexScreener, rugs as total losses, winner and loser alerts (`lab.paper.pumpfun`, under a minute; at most 8 GeckoTerminal and 20 DexScreener calls; reads only, no wallet) | `jobs.yaml`: `pumpfun` |
| 06:40 | pump.fun daily report, `reports/pumpfun/latest.json` and its card (`lab.paper.pumpfun --report`, seconds) | `jobs.yaml`: `pumpfun-report` |
| always | real-time pump.fun collector, PAPER: every creation, curve trade, completion and migration from a public Solana RPC websocket into `/srv/pythia-data/pumpfun_rt/`, plus the live shadow book (`lab.pumpfun_rt.collector`; reads only, no wallet) | container `pythia-pumpfun-rt`, see "Real-time pump.fun lab" |
| every 10 min | real-time pump.fun collector health: trades and heartbeat written in the last 10 minutes, else red and one alert (`lab.pumpfun_rt.health`, seconds) | `jobs.yaml`: `pumpfun-rt-health` |
| 01:00 | pump.fun factory F3, PAPER: an Optuna (TPE) search over the pipeline's building blocks, every trial a realistic book on the record with a 0.55 SOL wallet bootstrap (300 trials a night, `PYTHIA_PF_FACTORY_TRIALS`), the last 2 days held back for the night's top 3, the LightGBM settings of R2's labels, the factory paper books F3_<id>; at most 2.5 h, 3 CPUs, the `heavy` lock, resumable (`lab.pumpfun_rt.factory`) | `jobs.yaml`: `pumpfun-factory` |
| 06:40 | realistic pump.fun paper: the paper books' execution model refitted from the live bot's orders of the last 7 days (latency, failures, fees; a fixed fallback under 30 orders a side) and the daily line "live vs realistic paper" for P_pool0_wait, `reports/pumpfun_rt/realistic.json`, `.md` and `realistic_calib.csv` (`lab.pumpfun_rt.realistic`, seconds; reads the live files only) | `jobs.yaml`: `pumpfun-rt-realistic` |
| 06:50 | real-time pump.fun study: the 22 pre-registered rules and the model filter replayed with latency fills, the model retrained, `reports/pumpfun_rt/latest.json`, the shadow book's pick and the daily card (`lab.pumpfun_rt.study`; minutes per recorded day, at most the last 14) | `jobs.yaml`: `pumpfun-rt-study` |
| 04:45 | M4 shadow paper book, market-neutral on perps (`lab.paper.m4_ls`, 2 to 3 minutes, about 3 GB; rebuilds the xs_daily panel and retrains weekly into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-m4` |
| 05:30 | market-neutral M2 paper books (v1 and v2) | `/etc/cron.d/pythia-paper-ls` |
| 06:15 | forward report: every paper book and autopilot against its backtest (`lab.paper.forward_report`, seconds) | `/etc/cron.d/pythia-forward` |
| 06:30 | learning loop: demo-fill costs, forward evidence, monthly sweep refresh, weekly vol and monthly M2 retrain as challengers, nightly digest (`lab.ops.learn`, seconds; up to a few hours when a retrain is due) | `/etc/cron.d/pythia-learn` |
| 07:15 | model zoo: retrains the zoo models that are due, promotes a challenger only if better out of sample, shadow forecasts and scores, drift, the Models page report; posts promotions and drift (`lab.models.train --due`, about 5 minutes; longer on Sundays when M8, M8q and M10 retrain) | `/etc/cron.d/pythia-models` |
| 07:05 | Pokemon cards: price snapshot (`lab.collect.pokemon`, 15 to 45 minutes keyless, the API is slow and retried), then studies, fair value, forecasts, the paper collection and card alerts (`lab.pokemon.daily`, seconds at first, up to about 20 minutes with a year of history). Data and play money only | `/etc/cron.d/pythia-pokemon` |
| 06:20 | AI brief: one Sonnet call through the autopilot engine's metered `POST /api/ai/complete` (batch, half price) over the full fact sheet, 7-day calls for BTC, ETH and the autopilots' coins, scored against a base rate and the momentum rule; three lines for the digest, in German too when the chat is German (`lab.ai.brief`, minutes; see `docs/AI.md`) | jobs.yaml `ai-brief` |
| 06:40 | AI strategy critic: one Haiku call per autopilot (batch), its last 24 hours of orders against its rules; a card only for findings of medium or high severity, every finding logged and scored (`lab.ai.critic`, minutes) | jobs.yaml `ai-critic` |
| Sun 09:00 | AI weekly review: one Sonnet call (batch) over every study and live result, three proposed experiments in `reports/ai/weekly.md`, never run by anything (`lab.ai.weekly`) | jobs.yaml `ai-weekly` |
| Sun 11:00 | AI research director: one Opus call (effort high, batch) over every study summary and the trial ledger, 3 to 5 pre-registration drafts in `/opt/pythia-lab/proposals/` and a card, never run by anything (`lab.ai.director`, up to an hour) | jobs.yaml `ai-director` |
| always | the owner's questions in Telegram, answered by Sonnet from the same fact sheet, at most 40 a day (`lab.ai.chat`; reads only) | container `pythia-ai-chat`, see "Questions in Telegram" |
| every 15 min | local language model kept up: llama.cpp's server with Qwen3 4B Instruct (Q4_K_M) on 127.0.0.1:8091, 3 CPUs at a low share, 4 GB; downloads the pinned model once (`local-llm.sh up`, nothing while it runs as it should) | `jobs.yaml`: `local-llm` (host), see "Local language model" |
| after each news collect | the local model tags the new headlines with a topic and a relevance for the lab, 1 to 5 (`lab.ai.local --news`, about a minute for 100 headlines on the VPS) | `jobs.yaml`: `llm-news` |
| Sun 05:40 | cost calibration from the recorded books, report only | `/etc/cron.d/pythia-costs` |
| 02:20 | feature store D3: caches the finished UTC days of the recorded books (five venues), Kraken trades, funding, premium, open interest and liquidations as hourly features in `/srv/pythia-data/features/`, only days that are new or whose raw files changed, then `features/coverage.json` (`lab.features build`, about a minute, 1.8 GB at most; the `heavy` lock) | `jobs.yaml`: `features` |
| 03:00 | strategy factory F2, small-account mode: 60 new genomes for 40 and 100 EUR wallets on BTC, ETH, SOL, SPYx, QQQx, PAXG and USDC at Jupiter's real costs, four held-back checks against holding SPYx and BTC, the 40 EUR shadow wallets stepped and reviewed, `reports/smallaccount/factory.md` (`lab.factory small`, seconds; the `heavy` lock, resumable) | `jobs.yaml`: `factory-small` |
| 03:50 | model factory G2: new model specs (target of M8, M10, M12 or the strategy factory's 7-day forward return, a feature subset with G1's trees, LightGBM, ridge or logistic regression, a training window), each a trial in `models/factory/ledger.jsonl`, a purged walk-forward 2021 to 2023 against the baseline and the zoo model it would replace, at most 2 held back (2024 to 2026-06, DM p under 0.05 over all trials), passes as shadows next to the zoo, `reports/models/factory.md` (`lab.models.factory`, 25 minutes of search by `PYTHIA_MODEL_FACTORY_BUDGET`, 3 CPUs, 6 GB, the `heavy` lock, resumable; paper only) | `jobs.yaml`: `model-factory` |
| Sun 06:00 | leak check T1: every feature of the store, the candle windows, the zoo's feature builders (M8, M10, M12), the active G2 shadows' specs, the paper books' weight functions and their panel run on the full data and on copies with every value after t shuffled, shifted, missing or cut; anything at or before t that moves is a leak, a red line `leak <kind> <name>` in the health check; `reports/leak/latest.md` (`lab.leak`, minutes, the `heavy` lock; no trial). The factories check their genomes and specs before each held-back look (`factory/leaks.jsonl`, `factory/small/leaks.jsonl`, G2's `holdout.jsonl` status `leak`) | `jobs.yaml`: `leak-check` |
| 12:00 on the 1st | M1, newer model techniques against the incumbents in the ML image `pythia-lab-ml`: Chronos-Bolt and TimesFM 2.5 zero shot, TabPFN v2 and CatBoost in the model factory and the pump.fun zoo's walk-forward, the small account's regime choice, conformal intervals and a sizing on them, meta-labelling of the factory survivors, `reports/models/modern_m1/` (`lab.experiments.modern_m1`, 2 to 4 hours, 3 CPUs, 6 GB, the `heavy` lock; off until the image is built, see "The ML image") | `jobs.yaml`: `modern-models` |
| 05:00 | strategy factory, forward shadow step: appends the new days to each shadow book, decides those with 30 days (`lab.factory shadow`, seconds) | `/etc/cron.d/pythia-factory` |
| Sun 07:30 | strategy factory, weekly run: 300 new genomes in sample, six held-back checks, shadow review, report and digest (`lab.factory`, about a minute) | `/etc/cron.d/pythia-factory` |
| after the learning loop | daily digest to the operator's webhook (`lab.ops.notify`, seconds); off since the morning briefing replaced it, `jobs.py run notify --force` still sends one | `jobs.yaml`: `notify` (off) |
| 09:00 Berlin | morning briefing to Telegram and Discord: pump.fun Alpha phase, real-money accounts, paper and autopilots, lab, research factory (F3, F2 and the allocator), Pokemon, CS2, coins, stocks and ETFs, news, one overview chart; the summary line on top worded by the local model when every number in it is in the facts, else the template (`lab.ops.briefing`, seconds, up to 60 s more for the model; hourly 06 to 09 UTC, sends only in the hour that is 9 in Berlin, once a day) | `jobs.yaml`: `briefing` |
| 20:00 Berlin | lab card "🧠 Labor" to Telegram and Discord: what the research factories (F3 pump.fun, F2 small wallets), the model zoo and the allocator did today, from their reports, at most 8 lines, one sentence of the local model on top under the same number rule (`lab.ops.labor`, seconds; at 18 and 19 UTC, sends only in the hour that is 20 in Berlin, once a day; the bot's #labor, else #briefing; category "lab") | `jobs.yaml`: `labor` |
| 10:30 daily | T4 order book depth: Binance USD-M `bookDepth` (a snapshot about every 30 s of the notional within 0.2 % and 1 to 5 % of mid) of the lab's perps (`lab.collect.um_metrics`' symbols and the 20 lab coins) from 2023-01-01, each zip checked against its sha256 `.CHECKSUM` (a failed one is fetched again next run), the new days first, then the backfill oldest first, at most 60,000 files a run, resumable by symbol and month; before fetching it lists the archive and estimates the stored size (`book_depth/estimate.json`) and fetches nothing while the whole history would pass 40 GB (exit 1, a red `feed book-depth` row); also Binance's delisting and monitoring-tag announcements and the perps whose files stopped, a point-in-time table `book_depth/delistings.parquet` (`lab.collect.book_depth`, about 35 GB and six runs for the backfill, then minutes) | `jobs.yaml`: `book-depth` |
| 22:30 Mon to Fri | ETF closes: the lab's copy in `/srv/pythia-data/etf/daily` downloaded again after the US close, every symbol the ETF study, the small-account books and studies, `lab.history` and the briefing read, one at a time; a symbol that fails or returns an error page keeps its old file; exit 1 only when all fail; no study (`lab.collect.etf_daily`, under a minute) | `jobs.yaml`: `etf-daily` |
| hourly :35 | T12b every perp's listing and hourly funding history on Hyperliquid (live and delisted, from 2023-05-12) and Kraken Futures (every `PF_` perpetual, the endpoint's year and on), for T12 (`lab.collect.perps_all`, public endpoints, no key): at most 500 Hyperliquid requests a run, one every 3 s (under its weight limit, never at the same time as `free-hyperliquid`), the caught up coins one page each and the rest continuing the backfill coin by coin; at most 120 Kraken requests a run, one a second, a symbol again after 12 h. The backfill takes about a day of runs, then a run only appends. Resumable (each run continues from the stored rows; atomic writes), point in time (`lab.collect.pit`'s columns, one row per hour, the first value wins). A delisted Hyperliquid coin ends at its last settlement that is not 0/0 (Hyperliquid keeps writing 0/0 for it to today) and is not fetched again; a Kraken symbol that leaves the list keeps its history and last day. `lab.collect.perps_all.on_venue(listings, day)` gives T12's universe of a day | `/srv/pythia-data/free/perps_all/<venue>/funding/<coin>.parquet` and `listings.json` (first and last listed hour and day per coin), `free/perps_all/health.json` with coins done and left per venue (feed row `perps-all`, max 1 d old, dataset `perps-all`); `jobs.yaml`: `free-perps-all` (alert false) |
| 00:00 and 12:00 daily | T10 xStocks record of the small books' token (SPYx): the issuer's quote, multiplier, halt flag, proof of reserves, oracle feed ids and corporate actions from xStocks' keyless public API (`lab.collect.xstocks`, about 7 requests, seconds), point in time (`lab.collect.pit`), the 00:00 run at the small books' decision time; then the premium to SPY's last close next to R10's and S2's series (one trial in R5's registry) | `/srv/pythia-data/free/xstocks/` (feed row `xstocks`, dataset `xstocks`, max 14 h old), `reports/xstocks/latest.md`; `jobs.yaml`: `xstocks-collect` |
| every 2 min | real-money fills of Kraken and Alpaca autopilots to Discord (`lab.ops.notify --live-fills`, reads the engines' state; the bot's #konten and a DM, else the webhook; nothing without either) | `jobs.yaml`: `discord-live-fills` |
| always | Pythia's own Discord bot: lays out the owner's private server in German and English, keeps the channel map, answers the read-only slash commands `/status`, `/trades`, `/konten`, `/lab` for the owner only, in the channel's language (`research/discord`, 256 MB) | container `pythia-discord-bot`, see "Discord bot" |
| every 10 min | forward report, new study verdicts, model decisions and new headlines to the bot's channels (`lab.ops.discord_feed`, seconds, reads files only; nothing without the bot token) | `jobs.yaml`: `discord-feed` |
| hourly :12 | CS2 skins: Skinport snapshots and sales history, Steam prices for the watchlist, then models (refit daily), alerts, the play-money portfolio (weekly) and the board for the app (`lab.collect.cs2`, then `lab.cs2.run`; 2 Skinport requests and up to 100 Steam requests, about 6 minutes) | `/etc/cron.d/pythia-cs2` |
| 14:40, 20:40 | CS2 Steam market: the day's Steam price snapshot from csgotrader's public file, then trends, trend alerts with Steam and Skinport links, and a summary card with a chart (`lab.collect.cs2 --steam-market`, then `lab.cs2.trends`; 2 GETs, seconds; the second run only catches a late rebuild) | `jobs.yaml` only (`cs2-trends`) |
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
research/ops/deploy_ops.sh     # jobs.py, jobs.yaml, notify.py, i18n.py, system_health.sh, discord-setup.sh, discord-bot.sh (+ discord/) in /opt/pythia-ops, then render
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
| `jobs.py disk [--now]` | size and growth per dataset, the fall in free space over 3 and 7 days, the untracked use |
| `jobs.py prune [--dry-run]` | the retention rules |
| `jobs.py backup [--dry-run]` | archive the important state, rotate |
| `jobs.py restore-test` | unpack the newest archive into a temporary folder, compare every file's checksum |

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
- **Real-money controls read only.** A plain lab job (lab kind, the code at
  `/opt/pythia-lab`, no env file, network or volumes: the only kind the research
  agent may add) still mounts the whole data folder, but every real-money control
  that exists is mounted again read only on top of it (`LIVE_CONTROLS` in
  `lab/ops/jobs.py`): `autopilot/`, `autopilot-safe/`, `engine/`, `live/`,
  `pumpfun_rt/idl/`, the KILL files, `reports/pumpfun_rt/live_settings.json`, the
  sweep's `families_summary.json` and `tsmom_tranches.json`, every `signals/*_live/`
  and the signal folder each twin copies. Jobs with env files, a network,
  volumes or their own code mount run code the agent cannot change and are left
  as they are.
- **Volumes.** A volume whose host path does not exist stops the run before it
  starts (docker would create it as an empty folder).

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
full within 14 days at the faster fall in free space over the last 3 or 7 days
(the whole disk, not only the tracked folders: docker images and caches count),
when a dataset is over its `max_gb`, or when the newest file of a dataset with
`max_age_h` is older than that many hours (`etf/daily`, kept fresh by `etf-daily`, and `pokemon` have one
too). The disk row also says how much is used outside the tracked folders
(`untrackedGb` in `_ops/disk/latest.json`). A dataset with `retention_days` loses files older than that (by
modification time, only names matching its `pattern`, never through a
symlink) in the nightly `prune` job; the others are never deleted from. See
it first: `python3 /opt/pythia-ops/jobs.py prune --dry-run`.

## Backup

The nightly `backup` job archives the state that cannot be rebuilt from
market data (the engine and the safe account (`engine`, `autopilot-safe`), the
autopilot, the model registry and published models, the paper books and the
CS2 play-money portfolio, engine signals, the learning loop's ledgers, the
factory's trial ledgers including the pump.fun F3 ledger (`pumpfun_rt/factory`),
the live bot's `reports/pumpfun_rt/live_settings.json`, the Discord channel map
`discord/channels.json`, the forward evidence) into
`/srv/pythia-backup/pythia-state-<UTC time>.tar.gz`, mode 600, with a `.sha256`
and a `.json` manifest that holds the sha256 of every file. The engines'
rolling `state.json.bak-*` copies stay out. Each archive is read back before it
is kept. It keeps the newest of each of the last 7 days and of each of the last
4 weeks (`keep_daily`, `keep_weekly`). The list is `backup.include` in the
table; `<data>/_ops/backup/latest.json` lists what was missing.

Off the server: `research/sync-to-pc.sh` copies the newest archive to
`<PYTHIA_LOCAL>/_backup` on the PC after the data pull, by checksum (a local
copy counts only if its sha256 is the server's; a fresh copy is checked before
it is kept; the newest 7 stay, `PYTHIA_BACKUP_KEEP`), then leaves a receipt in
`/srv/pythia-backup/offsite.json`. A copy that arrives with another checksum is
dropped and the sync exits non-zero.

Restore test: the monthly `restore-test` job (the 1st, 03:40 UTC, under the
backup's lock) unpacks the newest archive into a temporary folder under
`/srv/pythia-backup`, compares every file's sha256 with the manifest and the
archive's with its `.sha256`, deletes the folder and writes
`<data>/_ops/backup/restore.json`. Run it by hand with
`python3 /opt/pythia-ops/jobs.py run restore-test --force`.

The health check has three lines while the backup job is on: `backup` (red if
an included entry was missing), `backup off-server` (red without a receipt, if
the receipt's checksum is not the server's, or once the PC copy is behind the
newest archive for more than `backup.offsite_max_age`, 1 day) and
`backup restore` (red until the first test and after a failed one).

Restore one (on the PC the archive is under `_backup`; copy it to the server first):

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

**The live copy.** What real money runs does not come from `/opt/pythia-lab`,
which the research agent's rounds deploy, but from `/opt/pythia-live`, which
only the owner deploys, by hand: `research/ops/deploy_live.sh` copies
`research/lab` of a clean checkout (default `/opt/pythia-src`) there, owned by
root, with the same sha256 manifest check, and first lists the commits since the
live copy that touched `research/lab`. It refuses while something runs from the
copy (`--force` overrides); stop the live service first and start it again after.
The jobs `paper-families`, `paper-live-copy` and `pumpfun-live-simulate` mount it
read only at `/app` (`code: false` plus `volumes` in the table), and so does the
live service (below). Deploy it before `deploy_ops.sh` installs a table that
mounts it: a missing `/opt/pythia-live` stops those jobs.

```bash
bash /opt/pythia-src/research/ops/deploy_live.sh --dry-run
bash /opt/pythia-src/research/ops/deploy_live.sh
```

## Real-time pump.fun lab

PAPER by default. `lab.pumpfun_rt` (see `research/lab/results/pumpfun_realtime.md`
and the pre-registration `results/pumpfun_realtime_plan.md`) records pump.fun
as it happens and trades it on paper through one trading pipeline (signal,
filter, sizing, risk limits, entry, exits) that a live executor would share.
The live executor (`live_exec.py`) runs only in its own service
(`live_service.py`), which the owner starts by hand; it is LOCKED unless the
owner does every step under "Live trading (locked)" below. The collector never
holds a wallet, reads a key, signs or sends anything; its only network is a
public Solana RPC websocket (`logsSubscribe`, read only), Telegram for the
cards and the engine's metered AI endpoint for the name categories.

The collector is a long-running container, not a job. The image needs
`aiohttp` (in `research/lab/requirements.txt` since this lab), so rebuild it
once, then start the container:

```bash
docker build -t pythia-lab /opt/pythia-lab
docker run -d --name pythia-pumpfun-rt --restart unless-stopped --cpus 1 --memory 1g \
  --env-file /etc/pythia/alerts.env \
  --log-opt max-size=20m --log-opt max-file=3 \
  -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.pumpfun_rt.collector
```

The lab code is bind-mounted, so after `research/ops/deploy_lab.sh` a
`docker restart pythia-pumpfun-rt` loads the new code (the restart is a gap in
the record, which is written down and left out of every number). Logs:
`docker logs --tail 50 pythia-pumpfun-rt`; state:
`/srv/pythia-data/pumpfun_rt/heartbeat.json` (streams connected, messages,
rows per table, reconnects, gaps, the shadow book's totals).

Settings (environment, all optional; put them in an env file and add
`--env-file` to the run line):

| Variable | Default | What |
|---|---|---|
| `PYTHIA_SOLANA_WS` | `wss://api.mainnet-beta.solana.com` | the websocket; the public endpoint documents 40 connections, 100 requests per 10 s and 100 MB per 30 s per IP and says it is not meant for production. A provider's URL (with its key) can replace it; the key then lives only in that env file |
| `PYTHIA_SOLANA_WS_URLS`, `PYTHIA_SOLANA_TOKEN` | unset | a paid low-latency provider (the owner's decision, docs/PUMPFUN-LIVE.md section 10): comma-separated websocket URLs, a `{token}` in a URL is filled from `PYTHIA_SOLANA_TOKEN`; the links spread over them and the public endpoint stays on as a fallback link (`PYTHIA_PF_PUBLIC_FALLBACK=0` drops it). Only scheme and host are ever logged |
| `PYTHIA_SOLANA_COMMITMENT` | confirmed | `processed` is faster (about 50 slots less behind on the public endpoint in a probe); a processed transaction is rarely dropped with its fork |
| `PYTHIA_SOLANA_GRPC_URL`, `PYTHIA_SOLANA_GRPC_TOKEN` | unset | a Yellowstone gRPC (Geyser) feed next to the websockets (`lab/pumpfun_rt/geyser.py`); needs `grpcio` in the image, else the websockets go on alone. The heartbeat's `first_by_source` shows which feed was first |
| `PYTHIA_PF_LINKS`, `PYTHIA_PF_AMM_LINKS` | 3, 2 | parallel connections per program; the public endpoint drops a connection every minute or two, the record has a gap only when all of a program's links are down at once |
| `PYTHIA_PF_AMM` | 1 | 0 stops the PumpSwap stream (the post-migration rules then have no data) and halves the traffic |
| `PYTHIA_PF_BUDGET_GB` | 40 | size budget of `pumpfun_rt/`; whole days go, oldest first |
| `PYTHIA_PF_SHADOW` | 1 | 0 records only, without the live shadow book |
| `PYTHIA_PF_META` | 1 | 0 stops fetching token metadata (IPFS uris through gateway.pinata.cloud, at most 1 a second, 64 KB; kept: the flags and, since Y14, the normalised X, telegram and website links) |
| `PYTHIA_PF_PRIORITY_SOL`, `PYTHIA_PF_LAT_MEDIAN_MS`, `PYTHIA_PF_LAT_LO_MS`, `PYTHIA_PF_LAT_HI_MS` | 0.001, 1000, 400, 3000 | the fill model's priority fee and latency (changing them changes the study; the plan's numbers are the defaults) |

Traffic: about 1 MB/s inbound (90 GB a day), most of it failed transactions
the endpoint sends along and PumpSwap trades of old pools that are dropped.
Disk: a day of record is a few hundred MB of parquet; the study merges a
finished day's part files into one file per table.

The jobs are in `jobs.yaml`:

| Job | When | What |
|---|---|---|
| `pumpfun-rt-health` | every 10 min | the collector wrote trades and its heartbeat in the last 10 minutes |
| `pumpfun-rt-categories` | 06:20 | yesterday's new token names into six categories, Claude Haiku 5.5 through the engine's `POST /api/ai/complete` (Batches; the engine's budget applies, a refusal is not a failure); names classified before are not asked again; cache `pumpfun_rt/categories/cats.jsonl`, report `reports/pumpfun_rt/categories.json`; usually well under $0.20 a day, capped at $0.40 a run |
| `pumpfun-factory` | 01:00 | F3 (`lab/pumpfun_rt/factory.py`): Optuna's TPE over entries (migration with a 0 to 60 s delay and the pool wait, a fresh pool by its age), filters (R2's win and rug models with thresholds, Y10's trend models and market heat, pool SOL, distinct buyers, Y16's R3 rule, the block list without its mint lines), exits (take profit, stop, time stop, Y12's lock, a partial sale) and R2's sizing (5 to 25 %, 1 to 3 open, brake on/off); each trial a realistic book in one replay per batch, walk-forward by UTC day, scored by the median 30-day end wallet from 0.55 SOL less the chance of losing 80 %; every trial in `pumpfun_rt/factory/ledger.jsonl` (only grows), the bar deflated by all trials ever, the last 2 full days held back for the night's top 3; the LightGBM settings of R2's labels, adopted into `pumpfun_rt/factory/params.json` (the daily retrain reads it) only when better in 4 of 5 purged folds and on the held-back days; winners as paper books F3_<id> (at most 5, 0.55 SOL each, the weakest retired after 14 days without beating P_pool5_top30t_sw10o3n, 14 days ahead written to `factory/proposals/`, never live); `reports/pumpfun_rt/factory.{md,json}`; 300 trials (`PYTHIA_PF_FACTORY_TRIALS`), at most 2.5 h, 3 CPUs, the `heavy` lock, the Optuna journal on disk (a rerun the same night does the trials left) |
| `pumpfun-rt-realistic` | 06:40 | R1: the realistic paper model (`lab/pumpfun_rt/realistic.py`) refitted from the last 7 days of `live/pumpfun_rt/measured.jsonl`, the calibration line live vs realistic paper for P_pool0_wait (calibrated: median P&L difference per matched trade within 5 points over 7 days); R2: the small-wallet paper books' wallets in SOL and EUR; F3: the factory books' wallets; the collector re-reads `reports/pumpfun_rt/realistic.json` every 10 minutes |
| `pumpfun-rt-study` | 06:50 | the 22 rules and the 12 pipeline strategies replayed over the last 14 days (latency fills, doubled latency, tripled priority fee), the bar, live readiness per strategy, each strategy's capture ratio, `reports/pumpfun_rt/latest.json`, the decision rows for the retrain (`pumpfun_rt/rows/latest.parquet`) and X14's early rows, paths and step rows (`pumpfun_rt/rows/early.parquet`, `steps.parquet`, `paths.npz`; paths and steps of about two days' worth of tokens, a hash sample) |
| `pumpfun-rt-retrain` | after the study | purged walk-forward per label and feature set (base, wallet reputation, name categories; a set only where it wins out of sample), the models for the shadow books, `reports/pumpfun_rt/models.md`; X14 (`results/pumpfun_early_exit_plan.md`): early detection and the 38 exit policies, `reports/pumpfun_rt/early_exit.md`, the early and hazard models with the in-sample k* for P_early10, P_early30, P_press10_hz and P_pool60_hz; R2 (`results/pumpfun_smallwallet_r2.md`): every label with execution in it at the realistic entry and exit (the study's `<label>_r` columns and `rows/select.parquet`), the old labels' models as `<name>_ideal` in `models/pumpfun_rt/ideal/` until 2026-11-07, side by side in the reports; A1 (`results/pumpfun_adaptive_a1_prereg.md`): the model zoo tested on each new UTC day and the selector's pick per label (`reports/pumpfun_rt/zoo.md`, history in `models/pumpfun_rt/zoo/`, no book reads it yet), the strategy allocator's pick (`reports/pumpfun_rt/allocator.{json,md}`, a line on the card; never the live bot); then the daily Telegram card with its capture and precision line and the small-wallet paper wallets |

The collector re-reads the models, the pick and the categories every ten
minutes; no restart. The shadow books (every pipeline strategy and the study's
pick) write `paper/pumpfun_rt/ledger.csv` (since R1 the pipeline books realistic under their names,
the old ones as `<name>_ideal` until 2026-11-06); a paper trade at +200 % or better
is posted at once (at most one an hour).

Try the study and the retrain by hand without posting:

```bash
docker run --rm --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.pumpfun_rt.study --dry-run
docker run --rm --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.pumpfun_rt.retrain --dry-run
docker run --rm --network host --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.pumpfun_rt.categorize --dry-run
```

Kill switch (paper and live): `touch /srv/pythia-data/pumpfun_rt/KILL` (or
`/etc/pythia/pumpfun-kill`, mounted into the container). While it is there no
book buys and every open position is sold; remove the file to resume. The
app's kill button writes `/srv/pythia-data/reports/pumpfun_rt/KILL`, which
stops the live book only (the paper books go on); only deleting it on the
server allows live buys again.

### Live trading (locked)

Nothing below is done, and nothing in the code does it. The live executor
refuses unless every step holds; `live_exec.py check` says which do not. The
owner's step-by-step runbook, in German, for the small real-money TEST
(mode=test: a budget of at most 2 SOL, 0.5 SOL a day, 0.25 SOL a trade, 0.6 SOL
open, hard in code with or without `limits=wallet`, a simulation within 24 hours
instead of the readiness report) is
`docs/PUMPFUN-LIVE.md`. Below is the reference for both modes.

Read this first. pump.fun's own terms forbid bots and automatic access on
its website and API (sections 6.1 and 21(h) as of 2026-10-08). This lab uses
neither: it reads the public chain and would send plain buy and sell
instructions of the public programs to a public RPC endpoint, which those
terms do not speak to. The owner decides with that knowledge. Most new tokens
go to zero within minutes, faster bots land first, and every position must
be sized as a total loss. No bundles, tips, private relays or anything that
front-runs other users are used or allowed (the executor refuses such
endpoints).

1. Rebuild the image once after the deploy (`cryptography` signs, `solders`
   makes the key; both are in `requirements.txt`):
   `docker build -t pythia-lab /opt/pythia-lab`.
2. The owner makes the wallet himself, interactively, with the wallet tool (the
   only code that makes a key). `/etc/pythia` must not be readable by everyone
   (`chmod 700 /etc/pythia`); the tool refuses otherwise, never overwrites a
   file, writes the key with mode 600 and the public address to `<file>.pub`
   and `reports/pumpfun_rt/wallet.json`, and shows the backup once after YES:

   ```bash
   docker run --rm -it -v /etc/pythia:/etc/pythia -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro pythia-lab python -m lab.pumpfun_rt.wallet new --out /etc/pythia/pumpfun-keypair.json
   ```

   Fund it by sending SOL to the address (the app's "pump.fun wallet" page
   shows it with a QR code). Nothing in Pythia withdraws or transfers; the
   owner withdraws by importing the backup into his own wallet.
3. Put the program IDLs from github.com/pump-fun/pump-public-docs
   (`idl/pump.json`, `idl/pump_amm.json`) into `/srv/pythia-data/pumpfun_rt/idl/`.
   The executor compares them with what it builds and refuses on any difference.
   It builds only the documented 17-account trades: `buy_v3` and `sell_v3` on
   the bonding curve, `buy_exact_quote_in_v2` and `sell_v2` on PumpSwap (the
   legacy and v1 trades now need undocumented remaining accounts and are
   never sent; cashback coins, which take neither, are refused). Pool prices
   use the effective quote reserves (vault plus the pool's signed
   `virtual_quote_reserves`) everywhere, live and on paper.
4. Write the confirmation `/etc/pythia/pumpfun-live-ack` (mode 600).
   - TEST mode (docs/PUMPFUN-LIVE.md, step 5, has the exact template):
     `mode=test`, `strategy=auto` (the least-bad post-migration pool rule of
     the latest study report, today P_pool60) or a named strategy,
     `max_total_sol` (at most 2.0), `max_daily_loss_sol` (at most 0.5),
     `max_trade_sol` (at most 0.05) and the line
     `I accept that I can lose all of it`. A value above its maximum is refused.
   - FULL mode: `rule=P_...` and `max_daily_loss_sol` (at most 1 SOL, capped),
     and the strategy must be ready: `reports/pumpfun_rt/latest.json`, section
     `readiness`, says `ready: true` for it (14+ days of record, 300+ trades
     out of sample, positive with and without broken slots, every gate, 30+
     days of the live paper shadow inside the replay's band), the report at
     most 36 hours old.
5. Put `PYTHIA_PUMPFUN_LIVE=1` and
   `PYTHIA_PUMPFUN_KEYPAIR=/etc/pythia/pumpfun-keypair.json` (optionally
   `PYTHIA_PUMPFUN_RPC`, plain https, and the `PYTHIA_PUMPFUN_STAKE_SOL`,
   `_MAX_OPEN`, `_MAX_EXPOSURE_SOL`, `_MAX_DAILY_LOSS_SOL` caps, which only
   lower) into `/etc/pythia/pumpfun-live.env` (mode 600).
6. TEST mode: simulate (nothing is signed or sent; a buy and a buy-then-sell
   for the funded wallet against the newest pool the collector saw, through
   `simulateTransaction` on mainnet; the gate needs a success within 24 hours,
   on the strategy's own venue; `--pool` and `--mint` pick another pool,
   `--venue curve --mint <mint>` looks at the curve path):

   ```bash
   docker run --rm --env-file /etc/pythia/pumpfun-live.env -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/pumpfun-live-ack:/etc/pythia/pumpfun-live-ack:ro \
     -v /etc/pythia/pumpfun-keypair.json.pub:/etc/pythia/pumpfun-keypair.json.pub:ro \
     pythia-lab python -m lab.pumpfun_rt.live_exec simulate
   docker run --rm --env-file /etc/pythia/pumpfun-live.env -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/pumpfun-keypair.json:/etc/pythia/pumpfun-keypair.json:ro \
     -v /etc/pythia/pumpfun-keypair.json.pub:/etc/pythia/pumpfun-keypair.json.pub:ro \
     -v /etc/pythia/pumpfun-live-ack:/etc/pythia/pumpfun-live-ack:ro \
     pythia-lab python -m lab.pumpfun_rt.live_exec check
   ```

7. Give the engine that serves the app write access to the live page's folder
   (lower limits and the kill file): add
   `-v /srv/pythia-data/reports/pumpfun_rt:/data/reports/pumpfun_rt` to its
   `docker run` (the reports folder stays read only otherwise) and recreate it.
8. Start the live service by hand. It is a long-running container like the
   collector's, in no job, script or compose file. Since 2026-10-23 it runs
   with `--restart unless-stopped` (the owner's call): after a crash or a reboot
   docker starts it again, it adopts and sells whatever it held, and the gate
   decides as at every start; a `docker stop` keeps it down. The job
   `pumpfun-live-watch` (research/ops/pumpfun_live_watch.py) checks it every two
   minutes and posts at once when it is down, hangs, does not buy and why, when
   the 24 h test gate is about to shut, or when a position is stuck.
   It runs the owner's live copy of the code (`/opt/pythia-live`, read only,
   `deploy_live.sh`), never `/opt/pythia-lab`, which the research agent's rounds
   deploy, and sees exactly three files of `/etc/pythia`, read only: the wallet
   file, its `.pub` and the confirmation (the env files are read by docker on
   the host and never mounted).

   ```bash
   docker run -d --name pythia-pumpfun-live --restart unless-stopped --cpus 1 --memory 1g \
     --env-file /etc/pythia/alerts.env --env-file /etc/pythia/pumpfun-live.env \
     --log-opt max-size=20m --log-opt max-file=3 \
     -v /srv/pythia-data:/data -v /opt/pythia-live:/app:ro \
     -v /etc/pythia/pumpfun-keypair.json:/etc/pythia/pumpfun-keypair.json:ro \
     -v /etc/pythia/pumpfun-keypair.json.pub:/etc/pythia/pumpfun-keypair.json.pub:ro \
     -v /etc/pythia/pumpfun-live-ack:/etc/pythia/pumpfun-live-ack:ro \
     pythia-lab python -m lab.pumpfun_rt.live_service
   ```

   Switching a running service over (from the older command that mounted
   `/opt/pythia-lab` and all of `/etc/pythia`): kill switch, wait until nothing
   is open, `docker stop pythia-pumpfun-live && docker rm pythia-pumpfun-live`,
   `deploy_live.sh`, the command above, remove the kill files. Because the folder
   is no longer mounted, `/etc/pythia/pumpfun-kill` does not reach this
   container; use `touch /srv/pythia-data/pumpfun_rt/KILL` or the app's button
   (`reports/pumpfun_rt/KILL`), which it reads.

   It streams the two programs over its own connections
   (`PYTHIA_PF_LIVE_LINKS`, `PYTHIA_PF_LIVE_AMM_LINKS`, 2 each) and records
   nothing. Its log says `live: ON (test) for ...` or lists every reason it
   stays off; with any gate shut it still runs and keeps the app's status
   current, and trades only after a restart once fixed. `--once` checks the
   gate, writes the status and exits.

Caps in code: 0.1 SOL a trade (test 0.05), 5 open positions, 0.6 SOL exposure,
the daily loss stop (no buys for the rest of the UTC day; test at most 0.5),
the total budget stop (test at most 2.0, counted since the first live trade in
`live/pumpfun_rt/totals.json`), a 0.01 SOL fee reserve, the kill switch. The
app's limits (`reports/pumpfun_rt/live_settings.json`) can only lower them;
the engine refuses anything above the confirmation file and the lab takes the
lowest again. The gate is checked every minute; any failure stops new buys.
Before signing, `txbuild.check_own` refuses anything but a plain buy or sale
for the wallet itself (no transfer out, no close to another account).

What the live service writes: `reports/pumpfun_rt/live_status.json` (every
30 s: mode, on or off and why, address, getBalance, token holdings, open
positions, P&L today and in all, limits, stops), `live_trades.json`,
`execution.json` and `execution.md` (measured landing latency, slippage and
fees against the paper model's assumptions; the daily study adds its summary
to its report), and under `/srv/pythia-data/live/pumpfun_rt/` `orders.jsonl`
(with the signatures), `ledger.csv` (every trade tagged with its mode),
`measured.jsonl`, `totals.json`, `open.json` (positions to sell after a
restart) and `simulate.json`. Telegram (category Trades, also in quiet hours):
every fill and failure at once, tagged TEST in test mode with the measured
landing time; the daily loss and total budget stops; positions from before a
restart sold or not sellable; a daily card with the balance, P&L, trades and
measured against assumed latency.

To stop: the kill switch (app button, or `touch /srv/pythia-data/pumpfun_rt/KILL`;
`/etc/pythia/pumpfun-kill` reaches only a service started with the older command
that mounted all of `/etc/pythia`), wait until nothing is open, then
`docker stop pythia-pumpfun-live`. To allow buys again:
`rm /srv/pythia-data/reports/pumpfun_rt/KILL /srv/pythia-data/pumpfun_rt/KILL` (and
`/etc/pythia/pumpfun-kill`) on the server; the app cannot.

### On-chain live trading, stage 2 (locked)

The real-money trader for the owner's own Solana wallet (`lab.onchain.live_service`, container
`pythia-onchain-live`) is built and locked; nothing arms it. The owner's runbook, in German, with every
command, is `docs/ONCHAIN-STAGE2.md`, section 7. It swaps through Jupiter's `/swap/v2/build` only when every
gate holds (`python -m lab.onchain.live_exec check` lists the shut ones): `PYTHIA_ONCHAIN_LIVE=1`, the ack
`/etc/pythia/onchain-live-ack` (mode=test or mode=alpha, mints, max_total_usd at most 500, max_trade_usd at most 100,
max_daily_loss_usd at most 100, max_convert_usd at most 250, expires at most 90 days ahead, the acceptance
line), its own wallet file `PYTHIA_ONCHAIN_KEYPAIR` made with `python -m lab.onchain.wallet new` (never the
pump.fun wallet), a successful `live_exec simulate` within 24 hours, no kill file
(`/srv/pythia-data/live/onchain/KILL`, the app's `reports/onchain_live/KILL`, `/etc/pythia/onchain-kill`), the
owner's copy of Jupiter's IDL at `/srv/pythia-data/onchain/idl/jupiter.json` and its pin of Jupiter's deployed
program (`python -m lab.onchain.live_exec pin`, `live/onchain/jupiter_pin.json`; a new deploy of Jupiter stops
every signature until the owner pins again), plain https endpoints (Helius
Sender only `/fast?swqos_only=true&mev-protect=true`). A book trades only when the ack names it and
`reports/onchain/proof.json` says it passed the pre-registered evidence.

Before signing, `lab.onchain.guard` refuses anything but the planned swap (the whole message read back from
its bytes, every writable account on chain, the simulation's account diff of the wallet and all its token
accounts); there is no transfer in it. It runs from `/opt/pythia-live` with the same narrow mounts as the
pump.fun service (the wallet file, its `.pub`, the ack, the code read only) and no automatic restart. The
engine needs `-v /srv/pythia-data/reports/onchain_live:/data/reports/onchain_live` to write convert requests,
confirms and the kill file; it never signs.

It writes `reports/onchain_live/status.json` and `trades.json` (every 30 s), answers the app's converts in
`reports/onchain_live/convert/` (request, proposal valid 60 s, the owner's confirm, result), and keeps
`live/onchain/orders.jsonl` (every step), `ledger.csv` (every swap as the chain shows it), `journal.jsonl`
(baselines, deposits, unexplained differences), `days.json`, `simulate.json` and `taken/` (a confirmed
convert is marked there before it is signed, so a restart never sends it twice; a swap sent but not booked
before a stop gets an unread ledger row at the next start and is read back from the chain). `--once` only
checks the gate and writes the status: it never opens the wallet file. The job `onchain-live-watch`
(`research/ops/onchain_live_watch.py`) checks it every two minutes and posts at once when it is down, hangs,
does not trade and why, the simulation is about to expire, the ledger differs from the chain, an account is
frozen or a swap hangs; before the container ever existed it stays quiet.

The ack may also say `mode=alpha` (docs/ONCHAIN-STAGE2.md, section 8): then the books it names trade
without the proof, under the lower hard maxima `live_gate.ALPHA_MAX_TOTAL_USD` (100), `ALPHA_MAX_TRADE_USD`
(25) and `ALPHA_MAX_DAILY_LOSS_USD` (25); every other gate stays, a book's order above the swap cap goes as
several swaps, and every alpha swap posts its card to Telegram and Discord's real-money route. The service
also writes `reports/onchain_live/values.json` (the wallet's worth every 15 min) and, for every sent swap,
`live/onchain/execution.jsonl` (signal to send, send to land, base, priority and tip, out against the quote).
Two read-only jobs feed the app's Wallet tab and the comparison: `onchain-history` (every 5 min,
`getSignaturesForAddress` and `getTransaction` for the wallet's public address into
`reports/onchain/history.json`) and `onchain-execution` (daily, `reports/onchain/execution.md` against the
pump.fun bot's `reports/pumpfun_rt/execution.json` and Kraken's fees).

The long-term book `onchain_longterm` (L1, `research/lab/results/onchain_longterm_l1.md`): job `onchain-longterm`
after `paper-families` writes its signal and steps its 0.5 SOL paper twin; live, when the ack names it, its swaps
take the cheapest path (no Sender, no tip, at most 0.00002 SOL priority a swap, `live_exec.Trader.cheap`).

## Questions in Telegram

`lab.ai.chat` lets the owner ask Pythia questions in the same Telegram chat
the alerts go to. It reads only: the engine's `/api/state`, the lab's reports
and the AI jobs' files, and it answers through the engine's metered
`POST /api/ai/complete` (Sonnet 5.5, `job` "ask" in the ledger), so every
answer is under the same budget caps as everything else. It cannot place,
change or cancel an order, touch an autopilot or change a setting; a message
asking for that, or for a key, token, password or server detail, is refused
(`docs/AI.md`, "Questions in Telegram").

It is a long-running container, not a job: it long-polls the bot's
`getUpdates` and takes messages from `PYTHIA_TELEGRAM_CHAT_ID` only. Nothing
else may consume the bot's updates (no webhook set on the bot, no second
poller), or the two take each other's messages. It needs the engine on
`127.0.0.1:8788`, hence the host network:

```bash
docker run -d --name pythia-ai-chat --restart unless-stopped --network host --cpus 0.5 --memory 768m \
  --env-file /etc/pythia/alerts.env \
  --log-opt max-size=10m --log-opt max-file=3 \
  -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  pythia-lab python -m lab.ai.chat
```

After `research/ops/deploy_lab.sh`, `docker restart pythia-ai-chat` loads the
new code. Logs: `docker logs --tail 50 pythia-ai-chat` (one line per answer
with its cost, never the question text or the token). Files under
`/srv/pythia-data/ai/`: `chat.jsonl` (every question, its answer, model and
cost), `chat_state.json` (the update offset, saved before answering, so a
restart never answers twice), `chat_heartbeat.json` (every 5 minutes).

Settings (in `/etc/pythia/alerts.env` or with `-e`): `PYTHIA_AI_ASK_PER_DAY`
(40 questions a UTC day; refusals, /help and /real do not count),
`PYTHIA_AI_MODEL_ASK` (haiku, sonnet, opus), `PYTHIA_AI_EFFORT_ASK` (medium).
In the chat: `/help`; `/real ID` and `/notreal ID` score a finding of the
strategy critic. Without a container, `python -m lab.ai.chat --once` answers
what is waiting and exits; a `*/1` cron line of that works too, at the cost
of a container start a minute.

## Local language model

The metered AI jobs (`ai-brief`, `ai-news`, `ai-critic`, `ai-weekly`) are off since the API credit ran out. What
they gave the briefing comes from a local model now, with no credit and no key (`lab.ai.local`). It only words
things: the briefing's summary line, the lab card's top line and the news tags. It decides nothing, never touches
trading, never sees a key or a wallet, and a number in its text that is not in the facts it was given throws the
text away (the template is used, the reason is logged).

Where it asks, in this order:

1. **The owner's PC**, through the relay on the VPS (OpenAI-compatible at the relay's `/v1`), when
   `/etc/pythia/local-llm.env` has the relay and the client token and the relay's status route says the PC is
   online. The owner fills the file (mode 600, root); it is never in the repo:

   ```
   PYTHIA_LOCAL_LLM_RELAY_URL=<the relay's base URL on the VPS, without /v1>
   PYTHIA_LOCAL_LLM_TOKEN=<the relay's client token>
   # optional: PYTHIA_LOCAL_LLM_RELAY_STATUS=/status   PYTHIA_LOCAL_LLM_RELAY_MODEL=<the model name the PC serves>
   ```

   The status route counts as online when it answers 200 and its JSON, if it has `online`, `connected`,
   `pc_online`, `up` or `ok`, says true. The jobs `briefing`, `labor` and `llm-news` read the file (optional).
2. **The VPS model**: llama.cpp's server, container `pythia-local-llm`, Qwen3 4B Instruct 2507 in GGUF Q4_K_M
   (2.5 GB, a pinned file, revision and sha256 in `local-llm.sh`, the image pinned by digest), on
   `127.0.0.1:8091` only, 3 CPUs at CPU share 256 (everything else goes first), 4 GB memory, no swap, read only,
   no capabilities, the model folder `/srv/pythia-llm` read only (outside the data store, so no sync or backup
   carries it). The host job `local-llm` keeps it up every 15 minutes and downloads the model the first time.
   Before a start it checks that nothing else holds 127.0.0.1:8091 (and names what does), and a failed
   `docker run` leaves docker's own error in the job's log. `llm-news` exits 1 when every model call of a run
   failed, so a dead model turns the job red instead of reporting ok.
3. **No text**: every user keeps its template. `PYTHIA_LOCAL_LLM=off` does the same on purpose.

Kept up rather than started by each job: the jobs run in containers without docker, an idle server takes no CPU
and about 0.7 GB of its own memory (the model file is mapped and the kernel may drop it under pressure), and it
loads in about 3 seconds. Measured on the VPS with 3 threads (llama.cpp b11910, `--no-repack`): about 50 to 60
tokens a second in and 15 to 19 out, at most 3.2 GB; with the default weight repacking it held a second copy of
the weights (4.8 GB) at the same speed, hence `--no-repack`. A briefing summary takes 2 to 7 seconds, 100
headlines about 75 seconds in batches of 8.

Uses (every call one line in `<data>/ai/local_llm.jsonl`: when, what for, which backend, tokens, seconds, ok or
why not; never the text or the token):

- the briefing's summary line: the sections' few words and the cards' lines go in as facts, two short sentences
  in the briefing's language come back; one 60 s budget for German and English together;
- the lab card at 20:00: one sentence over its lines, same rule, 60 s;
- news: each headline of `<data>/ai/news/<day>.jsonl` (today and yesterday, UTC) gets a topic (bitcoin, ethereum,
  solana, memecoins, defi, stablecoins, etf, regulation, macro, exchanges, security, stocks, other) and a relevance
  for the lab from 1 to 5 in `<data>/ai/news_tags/<day>.json`; a headline the model skips is asked once more, then
  left. The briefing shows the three most relevant (untagged ones: those naming a coin, then the newest).

```bash
sudo /opt/pythia-ops/local-llm.sh up       # start it (what the job does); down, status, bench
sudo /opt/pythia-ops/local-llm.sh bench    # tokens a second and memory now
docker run --rm --network host -v /srv/pythia-data:/data -v /opt/pythia-lab:/app \
  --env-file /etc/pythia/local-llm.env pythia-lab python -m lab.ai.local --probe   # which backend answers, how fast
```

## Health check

`system_health.sh` looks at the containers, the recorder's streams, every job
of the table (late, failing, blocked or stuck jobs go red, through
`jobs.py checks`), the disk and every dataset's size and growth, each paper
book's last row, the model service and the engine's market data
(`dataHealth` in `/api/state`), and writes
`/srv/pythia-data/_health/system.json`. It never restarts anything. Each free
data source of the table's `feeds` section gets a row `feed <name>`: red when
its collector's `health.json` is missing, its last run or the newest value of
one of its tables is older than `max_age`, more steps than `max_gaps` are
missing in the last 7 days, a column is missing or a part of the run failed
(no row while its job is disabled; "not run yet", not red, while its job has never run and was
installed less than one schedule period plus an hour ago). Each feature, zoo
feature builder or paper book the weekly leak check found leaking (or could not
check) gets a red row `leak <kind> <name>` with the first moved time and column,
from `reports/leak/latest.json` (no row before its first report). The Lab
page shows it ("Is everything running?"); the PC gets it with the sync. Red
for two runs in a row posts to Telegram (below, "Health alarm"), and again
whenever another check is red for two runs while the first is still red.

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

The small-account mode (`lab.factory small`, job `factory-small`, 03:00,
F2) searches strategies for a 40 and a 100 EUR wallet with S1's and S2's
costs in its own ledger `/srv/pythia-data/factory/small/ledger.jsonl` (its
own bar), runs survivors as 40 EUR shadow wallets in
`/srv/pythia-data/factory/small/shadow/` and writes
`/srv/pythia-data/reports/smallaccount/factory.{md,json}`. It reads the
panel cache paper-families wrote the day before and Yahoo's ETF closes (the
lab's copy when Yahoo does not answer); a shadow steps only to the last day
every ETF close is at most 5 days old. 60 genomes a day by default
(`PYTHIA_FACTORY_SMALL_BUDGET`); a rerun the same day only does what is
left. `results/factory_small_seed/` (the first run, made in the agent
container) is merged first.

Since D3 the weekly search may also put features of the feature store
into its trees (`f.<name>`), only those whose coverage in
`/srv/pythia-data/features/coverage.json` spans half of its in-sample window.

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

## Feature store

`lab.features` (D3, see "Feature store (D3)" in `research/lab/README.md`) is
the lab's point-in-time feature source. The job `features` (02:20) writes
the hourly tables of every finished day of the recorded tables to
`/srv/pythia-data/features/<group>/date=YYYY-MM-DD/hourly.parquet` (book,
trades, perp, liq; about 150 KB a day) and rebuilds a day only when it is
new or its raw files changed (`_built.json` keeps their signature). It reads
the recorder's folders and never deletes them: raw retention stays as it is,
and a day the retention removed keeps its partition. Today is computed from
the raw rows when a study asks. `python -m lab.features report` writes
`reports/feature_store_d3/` (coverage and rank IC of every feature); nothing
it writes reaches an engine or money.

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

### Model factory (G2)

`lab.models.factory` (job `model-factory`, 03:50, the `heavy` lock) makes
new models without anyone writing one. Each run, in this order:

| Step | What it does | Writes |
|---|---|---|
| shadow | every member refitted on all known rows writes its forecast and the baseline's for the newest open day; forecasts whose outcome is known are scored against the baseline and the zoo's own logged forecasts (`models/zoo/<name>/shadow.jsonl`); 30 scored days make it eligible, 60 behind the baseline or the incumbent retire it; per target a Thompson draw over the incumbent and the eligible members | `models/factory/shadows.json`, `shadow/<id>.jsonl`, `picks.json` |
| search | specs drawn at random (the whole first run, a third afterwards) or mutated from a target's ten best, each one trial: a quarterly purged walk-forward 2021 to 2023 (a training label ends before the test block starts) against the trivial baseline and the zoo model it would replace, fitted in the same folds | `models/factory/ledger.jsonl` |
| held back | at most 2 a run of the screen passes see 2024-01 to 2026-06 (R6's lockbox from 2026-07 is never looked at), each look written before it is scored; a pass needs a lower loss than both with a Diebold-Mariano p under 0.05 divided by every trial in the ledger | `models/factory/holdout.jsonl` |
| admit | passes become shadow members, at most 2 a run and 6 at a time | `models/factory/shadows.json` |
| report | trials, passes, shadows, retirements, the allocator's picks; a line in the briefing's research factory card | `reports/models/factory.{md,json}` |

The search stops when the day's budget is spent (`PYTHIA_MODEL_FACTORY_BUDGET`
seconds, 1,500 in the table); a rerun the same day only uses what is left, and
every trial and look is on disk the moment it is made. The first run's 1,017
trials (`research/lab/results/model_factory_seed/`) are merged before the
first search, so they count on the server. The allocator's picks
are for paper books only; no book reads them yet, and nothing reaches the
engine, a live bot or money. A run by hand:

```bash
docker run --rm --cpus 3 --memory 6g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.models.factory --budget 300
```

### The ML image (M1)

Newer model techniques (Chronos-Bolt and TimesFM 2.5 zero shot, TabPFN v2
and CatBoost in the model factory `lab.models.factory`, conformal intervals,
meta-labelling) need torch, which the lab image does not carry. They run in
their own image, `pythia-lab-ml` (`research/lab/Dockerfile.ml`: the lab
image plus torch's CPU wheels and every package pinned), and only the job
`modern-models` uses it (monthly, `lab.experiments.modern_m1`, off until the
image exists). Build it once after the lab image, then switch the job on in
`jobs.yaml` (`enabled: false` out) and deploy the table:

```bash
docker build -t pythia-lab-ml -f research/lab/Dockerfile.ml research/lab
docker run --rm --cpus 3 --memory 6g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab-ml python -m lab.experiments.modern_m1 run --only conformal
```

The weights are pinned by revision and downloaded once into
`models/hub` (`PYTHIA_HUB_OFFLINE=1` forbids any download), the forecasts
cached in `models/fm_cache`; the report is `reports/models/modern_m1/`.
Nothing a book, the engine or a live bot reads changes; the verdicts are in
`research/lab/results/modern_models_m1.md`.

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

## Polymarket (Y4)

PAPER ONLY: Polymarket's public read-only endpoints (Gamma, CLOB), no
account, no wallet, no key, no order. Three jobs in the table, added
disabled (`polymarket-daily`, `polymarket-history`, `polymarket-study`);
method and results in `research/lab/results/polymarket.md`.

- `polymarket-daily` (05:15): snapshot of every open market with $1,000 of
  liquidity and both books of up to 2,000 candidates, the Claude forecaster
  (Sonnet 5.5 through the engine's metered endpoint, Batches, at most 300
  markets and $3 a run; about $0.002 a market), settle and step the two
  paper books, score Claude and the model against the market, the feed
  `reports/polymarket/latest.json` and the card (category Studies, big
  edges at most 3 a day). An engine that is down or a budget refusal only
  skips the forecasts.
- `polymarket-history` (Mondays 01:30) adds the markets resolved since the
  last run with their price history, at 8 requests a second
  (`PYTHIA_PM_RPS`), then `polymarket-study` refits the model the daily
  book uses (`<data>/polymarket/model/`).
- Data under `<data>/polymarket` (`PYTHIA_PM_DIR`); the daily job deletes
  whole days of books, then of snapshots, oldest first, over
  `PYTHIA_PM_BUDGET_GB` (6). The forecast ledgers, the paper books and the
  model are in the backup and never deleted.
- The resolved set is built on the PC once (several hours at 8 requests a
  second) and copied up, so the weekly job only adds new markets:

```bash
tar -C F:/PythiaData/agent-y4/polymarket -cf - resolved state.json model | ssh pythia-vps 'mkdir -p /srv/pythia-data/polymarket && tar -xf - -C /srv/pythia-data/polymarket'
```

- Switch on after the lab code is deployed: `enabled: true` on the three
  jobs, then `research/ops/deploy_ops.sh`. First run by hand, without a
  card:

```bash
docker run --rm --network host --env-file /etc/pythia/alerts.env -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.polymarket.daily --forecast --no-post
```

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
  again for each check that turns red later in the episode, and once when green again

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

**Discord.** With the bot (below) set up, Discord carries more and posts
through it; this webhook stays as the fallback. Without the bot, a second
destination for two things only: the morning
briefing and every real-money trade card (each pump.fun Alpha-phase buy,
sale and close, a leftover sold, and every fill of a Kraken or Alpaca
autopilot in live mode), as an embed coloured by outcome with its chart
attached. A webhook cannot send a direct message, so make a private channel
on your own server and give it a webhook; that channel is your "DM". A second
channel for the trades is optional. Then, as root:

```bash
/opt/pythia-ops/discord-setup.sh
```

It asks for the webhook URL(s) without showing them, writes
`PYTHIA_DISCORD_WEBHOOK` (and `PYTHIA_DISCORD_WEBHOOK_TRADES`, default the
same channel) into `/etc/pythia/alerts.env` (mode 600) and posts a test
message to each channel. The pump.fun live container reads the same file, so
restart it once (`research/ops/deploy_live.sh` or `docker restart
pythia-pumpfun-live`) for its trade cards to reach Discord. The switches in
the app hold for Discord too (Daily P&L for the briefing, Trades for the
trade cards); a failed post is logged and changes nothing else.

**Discord bot.** Pythia's own bot (`research/discord`, discord.py pinned in
its `requirements.txt`, image from `python:3.12-slim`) runs 24/7 in the
container `pythia-discord-bot`. It needs the Discord application the owner
made, invited to the owner's own server with Manage Channels, Manage Roles,
Manage Webhooks, View Channels, Send Messages, Manage Messages, Embed Links,
Attach Files, Read Message History, Add Reactions and Use Application
Commands (no Administrator, no privileged intents), and
`/etc/pythia/discord.env` (root, mode 600) with `PYTHIA_DISCORD_BOT_TOKEN`,
`PYTHIA_DISCORD_GUILD_ID` and `PYTHIA_DISCORD_OWNER_ID`. Start or update it,
as root, after `deploy_ops.sh`:

```bash
/opt/pythia-ops/discord-bot.sh        # builds the image, (re)starts the container
docker logs -f pythia-discord-bot     # "layout: ..." lines, then "slash commands synced"
```

The container gets the env file through `--env-file` (read by docker, never
mounted), `/srv/pythia-data/reports` read only and its own state folder
`/srv/pythia-data/discord` writable; `--restart unless-stopped`, 256 MB, read-only
root file system, no capabilities. It never sees a wallet, a key other than
its own token, or anything else of `/etc/pythia`.

At start and every six hours it lays out the server, creating only what is
missing and never deleting anything, in two language blocks, in this order:
🇩🇪 Übersicht (#briefing, #status), 🇩🇪 Echtgeld (#pumpfun-trades, #konten),
🇩🇪 Lab (#studien, #paper-buecher, #modelle), 🇩🇪 Sammeln (#pokemon, #cs2-skins),
🇩🇪 Markt (#news), then 🇬🇧 Overview (#briefing, #status), 🇬🇧 Real money
(#pumpfun-trades, #accounts), 🇬🇧 Lab (#studies, #paper-books, #models),
🇬🇧 Collecting (#pokemon, #cs2-skins), 🇬🇧 Markets (#news); each channel with a
topic in its language; the role `Pythia` for the bot; every category and
channel private (@everyone may not view, the owner and the bot may; other
overwrites stay); a pinned welcome post in both #status, in their language,
that says what goes where. The German categories of the first layout
(📊 Übersicht, 💰 Echtgeld, 🧪 Lab, 🃏 Sammeln, 📰 Markt) are renamed in place, so
they and their channels keep their ids; a German channel found outside its
category is moved in. A channel of the same name the owner made is used, only
made private and given a topic when it has none; an English channel is only
ever one in its 🇬🇧 category. When everything is there, the categories and
channels are put in this order (one call). The server icon is left alone.
The map of channel ids, `{"de": {...}, "en": {...}}` (plus the German map as
`channels`, what older code reads) and the owner's DM channel, is written to
`/srv/pythia-data/discord/channels.json`, which the lab reads at
`/data/discord/channels.json`. Pinning needs the newer permission Pin
Messages on some servers; without it the post stays unpinned and the log says so.
A restart (`discord-bot.sh`) applies a new layout by itself: it runs first,
and the script prints its map line.

What goes where (`DISCORD_ROUTES` in `lab.ops.notify`): the 09:00 briefing to
#briefing and as a DM to the owner; every real-money pump.fun card with its
chart to #pumpfun-trades and as a DM; Kraken and Alpaca live fills to #konten
and as a DM; the factory's, director's and Polymarket's study cards to #studien;
Pokemon alerts (with the card's picture) to #pokemon; CS2 alerts and the trend
summary to #cs2-skins; and from `lab.ops.discord_feed` (job `discord-feed`) the
forward report's summary to #paper-buecher, new study verdicts to #studien,
model zoo decisions to #modelle, new headlines to #news; the 20:00 lab card
(`lab.ops.labor`) to #labor (#lab in English) when the channel map has one
(`DISCORD_EXTRA_ROUTES`; the layout does not make it), else as the briefing. All as embeds coloured
by outcome, charts as attachments. Every route posts twice: the German card
to the German channel and the English card, built from the same data, to its
twin in the 🇬🇧 block (#konten to #accounts, #studien to #studies,
#paper-buecher to #paper-books, #modelle to #models, the others by the same
name); the chart goes with both. A DM is one message, the German embeds first
and the English ones under it, the chart once. Every embed has the same
layout in both languages: the title with the result first, the key numbers as
fields in a fixed order, the footer "Pythia · Alpha" ("Pythia · Alpha phase"),
the time. Cards built outside `lab/ops` and the pump.fun card module (Pokemon,
CS2, factory, director, model zoo) carry no English build yet and go to both
channels as built. Telegram stays in one language. The jobs that post get
`/etc/pythia/discord.env` as an optional env file (`jobs.yaml`); with
`PYTHIA_DISCORD_BOT_TOKEN` set they post through the bot's REST API, and when
the bot cannot deliver, the briefing and the trade cards still go to the
webhook. The app's switches hold for the bot too.

The pump.fun live service reads its env files at its start: for its trade cards
to go through the bot, add `--env-file /etc/pythia/discord.env` to its
`docker run` at the next planned restart (kill switch, wait until nothing is
open, stop, run again with the extra flag, remove the kill files). Until then its
cards reach Discord through the webhook as before.

The slash commands, only for the owner's user id (anyone else gets "nicht
erlaubt"), answer only to the one who asked, only read, and in the language
of the channel they were used in (English in a 🇬🇧 channel, German in a 🇩🇪
channel or the DM): `/status`
(pump.fun live on or off, mode, wallet, today's and the total P&L, stake,
open positions, from `reports/pumpfun_rt/live_status.json`), `/trades` (the last
10 real-money trades), `/konten` (the pump.fun wallet, live and paper
autopilots, the paper books from the forward report), `/lab` (the newest
study reports and the model zoo). No command can trade, arm, change a limit or
touch the kill switch. To stop the bot: `docker stop pythia-discord-bot`.

**Morning briefing.** At 09:00 Europe/Berlin, summer and winter time, once a
day (`lab.ops.briefing`, job `briefing`): yesterday's pump.fun trades with
P&L in SOL and euro (SOL/EUR from the engine or Kraken's public ticker),
wallet and stake; the real-money autopilots; the autopilots' table, the
forward test and real-money readiness; the model zoo and the study reports
new in the last two days; Pokemon, CS2, coins, stocks and ETFs, the newest
news headlines. Only from the files the jobs write and the engines' state, no
model is asked. A section whose data is missing or older than two days is
left out. It replaces the old daily digest after the learning loop (the job
`notify` is off) and moves the same snapshot, so "today" keeps counting.
See it without posting:
`docker run --rm --network host -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.ops.briefing --dry-run --force`.

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
`python3` on the host, and `i18n.py` next to it (the words of the messages in
English and German). Install with the health script (and again after an
update of `notify.py` or `i18n.py`):

```bash
install -m 755 research/ops/system_health.sh /opt/pythia-ops/system_health.sh
install -m 644 research/lab/lab/ops/notify.py /opt/pythia-ops/notify.py
install -m 644 research/lab/lab/ops/i18n.py /opt/pythia-ops/i18n.py
```

**Message language.** The messages follow the app's setting (Settings,
Notifications, Message language). `PYTHIA_ALERT_LANG=de` in
`/etc/pythia/alerts.env` (and the engine's environment) fixes German for every
job and the engine whatever the app says.

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

The engine that serves the API needs the same folder: add
`-v /srv/pythia-data/reports/notify:/data/reports/notify -e PYTHIA_DATA=/data`
to its `docker run` (see `docs/ALERTS.md`, section HTTP API).

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

### Steam market trends (daily, job `cs2-trends`)

Steam's own endpoint refuses the collector (above), and that is left alone:
no other user agent, no proxy, nothing that works around it. The Steam side
comes instead from the public price files of the open-source CSGO Trader
browser extension (`https://prices.csgotrader.app/latest/steam.json` and
`exchange_rates.json`; the extension downloads the same files for every
user). `steam.json` has, for about 34,000 items, the average Steam Community
Market sale price in USD over the last 24 hours, 7, 30 and 90 days, rebuilt
once a day (13:25 UTC on 2026-10-15); no volume. There are no published terms
or limits for the files: the job takes them once a day (about 0.6 MB
gzipped), names itself in the user agent, and the CS2 page and the reports
name the source. Should the owner of the files object, switch the job off
(`enabled: false` in `jobs.yaml`).

The job (table entry `cs2-trends`, 14:40 and 20:40 UTC, the second one only
catches a late rebuild) runs `python -m lab.collect.cs2 --steam-market` (the
day's snapshot, dated by the file's Last-Modified day, stored once) and then
`python -m lab.cs2.trends`: 1, 7 and 30-day changes (the source's windows
until our own snapshots cover the span), momentum against mean reversion by
group (cases, capsules, stickers, knives and gloves, skins by wear, price
tiers as a stand-in for rarity), the Steam against Skinport spread after both
fees (Steam keeps about 13 % and pays in wallet funds; Skinport 8 %, cash),
new cases and capsules and the cases around the latest drop. It posts a trend
alert when something is notable (top movers 15 % or more in a day, or 20 % off
the weekly average before there is a day-old snapshot; cases up 15 % in a
week; a new case or capsule; Steam to Skinport clearing 5 % after fees, or a
Steam premium far above its group), each item with its Steam market listing
and Skinport page, and once a day a summary card with a small chart (category
`cs2` in the app's notification switches). Information only.

| Path | What |
|---|---|
| `cs2/daily/steam_market/date=*.parquet` | the daily Steam snapshot (USD averages per window, EUR per USD), kept forever (about 1 MB a day) |
| `cs2/steam_market.json` | the last snapshot run |
| `cs2/trends/latest.json` | what the CS2 page shows; the hourly board carries it as `steamTrends` |
| `cs2/trends/alerts_state.json`, `alerts.jsonl` | alerts sent, 3-day cooldown per item and kind; the last summary day |
| `reports/cs2_trends/latest.{md,json}` | the daily report, also a lab feed |

Run once by hand, without posting:

```bash
docker run --rm --memory 3g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab sh -c 'python -m lab.collect.cs2 --steam-market && python -m lab.cs2.trends --dry-run'
```

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

## Extended crypto universe (W3)

The engine quotes, charts and books every coin of its configured crypto
universe. By default that is every pair the Alpaca paper account trades
(stablecoins and gold left out, 32 coins) plus the lab's five coins Alpaca
does not list, 37 in all. Alpaca's public crypto market data (v1beta3) is a
keyless feed source next to Kraken, so coins Kraken or Binance do not list are
still served; failover, sanity checks and `dataHealth` work per coin as
before. Demo orders still go to the Alpaca paper account only.

Choosing the coins, on both engines (the lab reads the same setting for the
signals it writes, so set it for the lab container too):

```bash
# a list, presets or both: default, alpaca, lab20, memes; commas, spaces or lines
PYTHIA_CRYPTO_UNIVERSE="alpaca"
PYTHIA_CRYPTO_UNIVERSE="lab20 BONK WIF"
# or a file in the same format, '#' starts a comment
PYTHIA_CRYPTO_UNIVERSE_FILE=/path/to/universe.txt
```

Put it in the engine's environment (compose file or env file), restart the
engine, and check the Data health card: every coin should show a source
within a minute. Feed order can still be set with `PYTHIA_FEED_QUOTES` and
`PYTHIA_FEED_CANDLES` (`kraken-ws,kraken,alpaca,binance,coinbase,bybit,okx`);
a coin is only asked of the sources that list it. The data host the engine
needs in addition: `data.alpaca.markets` (HTTPS, no key).

The lab's history already covers the extended coins that trade on Binance
(the backfill takes every USDT pair). To see what each coin has:

```bash
docker run --rm --memory 6g -v <data dir>:/data -v <lab checkout>:/app pythia-lab \
  python -c "from lab import universe as u; from lab.experiments import fam_common as fc; \
  [print(c) for c in u.coverage(fc.load_panel(), u.ALPACA)]"
```

The W3 study (`results/alpaca36.md`, pre-registered) runs where the daily
panel is cached, in about the time of the C16 study:

```bash
docker run --rm --memory 6g -v <data dir>:/data -v <lab checkout>:/app pythia-lab \
  python -m lab.experiments.alpaca36
```

It rewrites the part of `results/alpaca36.md` below the marker and writes
`<agent-strategies>/reports/alpaca36.json`; commit the markdown. A paper book
is added only if a candidate passes the pre-registered rules, in a separate
change.

The paper books can also be run on a universe as separate books, for a look
at what they would hold (`--dry-run` writes nothing). They keep their own
journals under `paper/<book>@<universe>/` and write no engine signal:

```bash
docker run --rm --memory 6g -v <data dir>:/data -v <lab checkout>:/app pythia-lab \
  python -m lab.paper.families --universe alpaca --dry-run
```

## Research agent

The lab keeps researching without the owner's PC: the jobs `agent-research` (Sunday
13:00 UTC, two hours after the research director's drafts) and `agent-care` (daily
08:15 UTC) run `research/ops/agent/run_agent.sh`, which starts Claude Code headless in
its own container (image `pythia-agent`, built from `research/ops/agent/Dockerfile` on
top of the lab image) and pays for it from the Claude API key in
`/root/pythia-agent-secrets/agent.env`. Its prompts are `research.md` (weekly: up to
three pre-registered studies, paper books for what passes, fixes) and `care.md` (daily:
failed jobs fixed with tests, the books and the live bot checked). Both jobs are off
(`enabled: false`) until the owner switches them on.

**What the agent can reach.** It runs as the unprivileged user `agent` (uid 10001),
every capability dropped, `no-new-privileges`, on its own Docker network
(`pythia-agent`, so not on the default bridge with the engines and the live bot), with:

| In the container | What | Access |
|---|---|---|
| `/work` | a fresh clone of main, made for this run | read and write |
| `/out` | `/srv/pythia-agent-out`, its only other writable folder: the report `/out/<mode>.md`, the rerun list `/out/rerun.txt`, `PYTHIA_REPORTS=/out/reports`, `PYTHIA_CACHE=/out/cache`, `PYTHIA_AGENT_OUT=/out/agent`, `PYTHIA_WRITE_ROOT=/out/data` (paper books, signals, models a study saves; `lab/data.py`) | read and write |
| `/data` | `/srv/pythia-data`, with every real-money control in it | read only |
| `/home/agent` | an empty tmpfs, gone after the run, so nothing it leaves there reaches a later run | read and write |
| `/snapshot/snapshot.md` | the host snapshot (failed jobs, containers, autopilots, the live bot's log), written by root outside every agent folder | read only |
| `/proposals` | the research director's drafts | read only |
| `/run/lock/pythia` | the job locks, to wait for `heavy` | read only |
| `/etc/claude-code/managed-settings.json` | no attribution lines in commits | read only |

What it cannot reach: the Docker socket, a git key, `/etc/pythia` (the wallet, its
confirmation, `alerts.env`), `/root/pythia-agent-secrets` (only `ANTHROPIC_API_KEY` is
passed in), `/opt/pythia-live`, `/opt/pythia-lab`, the engines' API ports (other
networks, or bound to the host's 127.0.0.1) and the pump.fun live container. Network: it
needs the Claude API (`api.anthropic.com`) and, for the care round's IDL comparison,
`github.com` and `raw.githubusercontent.com`; packages are baked into the image, so
no package mirror is needed at run time. Its network is a plain Docker bridge with
internet access; an egress allow list for those hosts would need a proxy in front
of it and is not set up. A spend limit on the API key in the Anthropic console caps
what it can cost.

**How a round is checked.** After the run, a container without network prints the
agent's commits as one mbox (`git format-patch --stdout`), which this shell writes into
the root-only `/opt/pythia-agent/run/`; no git runs on the host in the agent's clone.
The host applies the mbox in its own clone (`/opt/pythia-agent/trusted`) and checks, in
this order: main has not moved since the start; `guard.py`; gitleaks (pinned image, no
network) with the base's `.gitleaks.toml` and `.gitleaksignore`. Only when all of them
pass is the round pushed to main, merged into `/opt/pythia-src` and deployed:
`deploy_lab.sh` (retried while jobs run), then `deploy_ops.sh` when the job table
changed, each checked; a failed merge or deploy posts a clear notice and nothing after
it runs. The jobs in `/out/rerun.txt` (at most five, lab jobs) run only after a clean
deploy. **A round that fails any check is held: nothing is pushed anywhere.** Its mbox,
the reasons, the run log and the report stay root-only in
`/root/pythia-agent-held/<mode>-<stamp>/`, and Telegram gets a notice with the reasons
(paths and kinds, never the content). To take a held round after reading it:
`git am /root/pythia-agent-held/<mode>-<stamp>/round.mbox` in a clone, review, push by
hand.

`guard.py` (its docstring has the full rule) holds a round unless every changed path is
on its ALLOW list: `research/lab/lab/{experiments,paper,factory,collect}/**`,
`research/lab/results/**`, `research/lab/tests/**`, `research/lab/proposals/**`,
`research/lab/README.md` and `research/ops/jobs.yaml` under the job rules. Inside those it
still refuses `paper/live_copy.py`, `paper/families.py`, the results the families job
reads (`families_summary.md`, `family_*.md`, `tsmom_tranches.md`), git and scanner
control files, and every module that real money or a job with secrets runs: the import
closure (computed from the code on every run, `python3 guard.py --closure <repo> <rev>`
lists it) of every module in `lab/pumpfun_rt`, `lab/ops` and `lab/ai`, of the live
twin's two modules, and of the command of every job that is not a plain lab job (env
file, network, volumes, its own image, host kind, no code mount). On 2026-10-22 that
closure takes, out of the allowed folders: in `collect/` `__init__`, `cs2`, `flow`,
`pokemon` (the cs2-trends and pokemon jobs pass `alerts.env`); in `experiments/`
`__init__`, `alpaca_universe`, `cs2`, `equities_ranking`, `equities_training`,
`etf_trend`, `exit_overlays`, `families` and every `fam_*`, `flow_overlays`,
`intraday_equities`, `m2_v3`, `momentum2`, `overnight`, `picks`, `picks_ls`, `tsmom`,
`tsmom_tranches`, `vol`, `vol_daily` (the live twin's book, the learning loop on the
host network, the AI jobs, the model zoo); all of `factory/` (factory-shadow and
factory-weekly pass `alerts.env`; to give the factory back to the agent, run them
without the env file and post their digest from another job); in `paper/`
`__init__`, `experimental`, `families`, `forward_report`, `listings_book`, `live_copy`,
`pumpfun`, `tsmom` (the live twin, the forward report on the host network, the
listings and pump.fun paper jobs with `alerts.env`).

Why what remains cannot reach real money: (1) the agent's container sees `/data` read
only and holds no key; (2) code from the allowed folders is deployed only to
`/opt/pythia-lab`, while real money runs from `/opt/pythia-live`, which only the owner
deploys (`deploy_live.sh`): the live service, `paper-families`, `paper-live-copy` and
`pumpfun-live-simulate`; (3) no module that real money, a secret, the host network or a
volume runs may change (the closure above), so allowed code runs only in plain lab
jobs; (4) a plain lab job sees every real-money control read only (`LIVE_CONTROLS` in
`lab/ops/jobs.py`, "The job table" above); (5) the agent can add or change only plain
lab jobs running `python -m lab.<module>` of a module it may change, and can change no
job with volumes, env files, a network, a host kind or an image, nor `paper-families` or
`paper-live-copy`. What is left: a plain lab job running the agent's code can still
write the market data, caches and paper books the families job reads, so it could feed
the live twin's book wrong inputs; the engine's live caps (amount and maximum loss in
SAFETY.md) bound that, and the owner sees every deployed round in the git log.

The guard also holds a round for: a symlink or submodule, a file over 1 MB, a binary
file, a file named like live data or a secret (`orders.jsonl`, `ledger.csv`,
`measured.jsonl`, `state.json`, `*.env`, `*keypair*` and the like); an added line, a file
name or a commit message that looks private (public IPv4 and IPv6 addresses, e-mail
addresses also as `%40`, keys and tokens, `api-key=` values, any PEM `BEGIN` line, a
64-number key array also across lines, a 64 to 88 character base58 string, Windows,
`/mnt/c`, `/home/<name>` and `/Users/<name>` paths, and the owner's own patterns); an
allow marker (`gitleaks:allow`, `secret-scan:allow`) or an em dash in an added line; an
attribution line or an assistant's name in a commit message; an author or committer
that is not the owner's identity. The diff is read with `--text --no-renames
--no-ext-diff --no-textconv`, so neither `.gitattributes` nor a rename hides a line or
a path. Its tests: `python -m pytest -q research/ops/agent/test_guard.py` (Linux, git;
`scripts/security-scan.sh` runs them too). On the server,
`bash /opt/pythia-src/research/ops/agent/audit_cases.sh` proves every audit case against
a throwaway clone and the agent's container with temporary folders only (no round, no
push, no job): each case held, a clean round passing guard and gitleaks, the report never
read through a symlink or FIFO, `/data` readable and not writable.

Setup once, on the server as root:

```bash
umask 077
install -d -m 700 /root/pythia-agent-secrets /root/pythia-agent-held
# agent.env: the Claude API key and the commit identity's address (never in this repository)
grep '^ANTHROPIC_API_KEY=' /etc/pythia/alerts.env > /root/pythia-agent-secrets/agent.env
echo 'PYTHIA_AGENT_GIT_EMAIL=<the owner address>' >> /root/pythia-agent-secrets/agent.env
ssh-keygen -t ed25519 -N '' -C pythia-agent -f /root/pythia-agent-secrets/agent-deploy-key
# add agent-deploy-key.pub to the repository as a deploy key with write access
$EDITOR /root/pythia-agent-secrets/private-patterns.txt     # format below
chmod 600 /root/pythia-agent-secrets/*
install -d -m 700 -o 10001 -g 10001 /srv/pythia-agent-out
bash /opt/pythia-src/research/ops/deploy_live.sh               # before the table that mounts it
bash /opt/pythia-src/research/ops/deploy_ops.sh
```

`private-patterns.txt` holds what is private to the owner and must never be written into
this public repository: one pattern per line, a plain line is matched literally and
case-insensitively anywhere in an added line, a file name or a commit message, a line
starting with `re:` is a Python regular expression (case-insensitive), `#` starts a
comment. Put in at least the server's domain and IP address, the panel's path, the
pump.fun wallet's address and the owner's e-mail address, each on its own line. The
guard holds every round while the file is missing or empty.

`PYTHIA_AGENT_GIT_EMAIL` (and optionally `PYTHIA_AGENT_GIT_NAME`, default `SenseiIssei`)
is the identity the agent's commits must carry; a commit by anyone else holds the
round. Models and limits can be changed in `agent.env` without a deploy
(`PYTHIA_AGENT_MODEL_RESEARCH`, `PYTHIA_AGENT_MODEL_CARE`, `PYTHIA_AGENT_TURNS_RESEARCH`,
`PYTHIA_AGENT_TURNS_CARE`). Run logs: `/opt/pythia-agent/logs/` (root only, the last 40).
Run one by hand: `python3 /opt/pythia-ops/jobs.py --table /opt/pythia-ops/jobs.yaml run
agent-care --force`. Switch it on or off: `enabled` on both jobs and `deploy_ops.sh`.

The owner's own commits are checked by the pre-commit hook: install it once per clone
with `git config core.hooksPath scripts/hooks` (or `npm run hooks:install`).

## Task lanes

A lane task is one paid Claude Code run on one brief, landed only when the host's checks pass.
The runner, its rules and its tests are in `research/ops/lanes/` (R8, from the review
`research/lab/results/review_2026-10-27.md`): `run_lane.sh` (the shell: queue, run, report),
`lanes.py` (every rule, standard library, uses `agent/guard.py`), `lane.md` (the run's standing
rules), `task_template.md` (the task file) and `test_lanes.py`.

**The task file.** A header between two `---` lines, then the brief: `id`, `title`, `model`
(`claude-opus-5-5`, `claude-sonnet-5-5` or `claude-haiku-5-5`), `max_usd` (at most 30),
`allowed:` (globs of the files the run may change: `**` any folders, `*` inside a name, `{a,b}`),
`docs:` (read first, must exist on main), `tests:` (commands from the repository root, plain
chains of cd, python, pytest, npx, npm, cargo, bash), optionally `retry: no`. `run_lane.sh queue
FILE` checks it against main before it is queued, and the runner checks it again before it spends
anything: missing keys, a model outside the three, a glob without its folder (`*.py`, `**`), a
path outside the repository, an `allowed` entry that names only never-list paths, and every path
of the brief's `Files:` line that `allowed` does not cover (relative to `research/lab/` unless it
starts with a top folder or is a root file; "tests" needs a test file in the list). A refused task
costs nothing and the notice says why.

**The never list** (`lanes.NEVER`, fixed in code, no task list or retry can open it): the code
that signs, sends or limits real money (`pumpfun_rt/live*.py`, `txbuild.py`, `wallet.py`,
`fastpath.py`, `onchain/live_*.py`, `meme_live.py`, `wallet.py`, `tx.py`, `swapapi.py`,
`jupiter.py`, `guard.py`, `paper/live_copy.py`, `paper/families.py`, the engine's
`pumpfun_live*.rs`, `onchain_live*.rs`, `vault.rs`, `connectors/`, `execution/`, the server's
`guard*.rs`), their tests, `deploy_live.sh` and the live watchers, SAFETY.md, and the rules
themselves (`research/ops/lanes/`, the agent's `guard.py`, `run_agent.sh`, `audit_cases.sh`,
`Dockerfile`, `deploy_ops.sh`, `deploy_lab.sh`, gitleaks files, `.github/`, the hooks). A brief
that asks for one of them is refused at the queue (R1 would have been: the owner does those by
hand); a broad glob such as `research/lab/tests/**` is fine, the never list wins inside it.

**In the container.** The prompt is `lane.md`, the allowed list, the docs, the tests, the never
list and the brief (`lanes.py prompt`). `/lane` holds main's copy of `lanes.py`, `guard.py` and
`jobs.py` and the task, read only; before a commit the run calls `python3
/lane/research/ops/lanes/lanes.py check --task /lane/task.md --repo /work --tests`, which judges
the working tree against the base exactly as the host will: HOLD lines (fatal), DROPPED lines
(off the list) and WARN lines (a commit subject over 200 characters). `claude` runs with
`--max-budget-usd` set to the task's `max_usd`.

**On the host.** The commits as one mbox (a container without network), applied in the trusted
clone; then `lanes.py verdict`. Files outside the list or on the never list are **dropped**: the
commits are made again on the base, each limited to the kept files (`lanes.py prune`, a commit
left empty goes), judged again, and the notice and `reports/lanes/<id>.json` (`dropped`) name
them. What holds the whole run: the guard's private lines and file kinds (symlinks, binaries, over
1 MB, live-data names), an em dash, an allow marker, an attribution or a foreign author, a kept
lab module that newly imports a never-list module, a job table change against the guard's job
rules (with the task's list for the modules a job may run), nothing left, main moved, the task's
tests red (in the agent image, from the result, network `PYTHIA_LANE_TEST_NET`, default the
agent's), gitleaks. Then push, `/opt/pythia-src`, `deploy_lab.sh`, `deploy_ops.sh` when the job
table changed, as for the research agent.

**Trials (T14).** The run's container mounts the data folder read only, so `lab.metrics.register`
writes a study's trials into a copy, `/out/trials/registry.jsonl` (`PYTHIA_TRIALS_REGISTRY`, seeded
with the server's registry so the run's bar counts every trial). Right after the agent ends, held
or landed, `lanes.py trials` appends the copy's lines whose id `<data>/trials/registry.jsonl` lacks,
unchanged (register's rule: append only, the first id wins), and the log names the count: a held
or stopped study looked at the data too, and without this its trials were lost (67 of T5, T6, T7
and T10 merged by hand on 2026-10-28). A missing copy adds nothing.

**One retry.** A held run is queued once more as `<id>-retry` on the next cheaper model (Opus to
Sonnet, Sonnet to Haiku, Haiku none), half the `max_usd` (at least 1), the host's reasons at the
top of the brief, starting from the held commits (applied in the new clone without network), and
`retry: no`.

**The budget gate.** `/root/pythia-lanes/budget.json` is the owner's: `{"balance_usd": 40,
"reserve_usd": 10, "since": "2026-10-28T00:00:00"}`; every run adds its cost from Claude's JSON
(`total_cost_usd`, the cap when unreadable) to `spent.jsonl`. A run starts only if the balance
less what was spent since `since` exceeds the reserve plus its `max_usd`; with every run capped at
its `max_usd`, the balance cannot fall below the reserve (from 2026-10-24 to 27 it ended 78 USD
past it). `"paused": true` stops every start. `run_lane.sh report` writes
`reports/research/latest.json` (the briefing's lane card) from the records, the queue (a `HOLD`
file in a task's folder holds it) and the budget.

**Replay of 2026-10-26 and 27** (`replay_2026-10-27.json`, `lanes.py replay`, checked by the
tests). The review's 12 rejections: 7 paid (49.93 USD) and 5 unpaid. The task files are rebuilt
from the template (allowed from what the run changed, since those briefs are not in the
repository); for the 8 after the review the brief's own `Files:` line was used.

| Run | USD | Rejected for | Under the new rules |
|---|---|---|---|
| M1 modern models | 11.23 | `modern_m1.py`, ops README | accepted, ops README dropped |
| D3 feature store | 8.20 | binary Parquet fixtures | held (binary; the check says so before the commit), retry on Sonnet |
| D2 free data | 6.43 | `data_free_d2.py`, `lab/ops/jobs.py`, ops README | accepted, ops README dropped |
| 116 mini agent | | no task.md | refused at the queue |
| G2 model factory | 6.44 | ops README | accepted, ops README dropped |
| Y14 X links | 6.06 | ops README | accepted, ops README dropped |
| 001, 002, 003, 006 paper books | | nothing committed (local model) | refused at the queue (not a lane model: make it a job) |
| D1 history from 2017 | 6.84 | an em dash | held (the check says so before the commit), retry on Sonnet |
| F2 small factory | 4.73 | seed files | accepted (the seeds in the list) |
| H1 lean agent | 1.09 | agent README | accepted, agent README dropped |
| R1 real-money caps | 2.26 | the files its brief asked for | refused at the queue (never list), nothing spent |
| R2 to R7 | 17.03 and R7 | the files their briefs asked for | accepted, all six |
| G2 after R6 | 6.79 | gitleaks | held, retry on Sonnet |

Of the 15 paid runs that would start, 12 are accepted the first time (80 %), none is held for
or loses a file its brief asked for, and the 3 held ones fail on what the in-container check reports
before the commit. The four local-model tasks stay failures under any lane rule; recurring report
tasks belong in jobs.

**Setup once, on the server as root** (after `deploy_ops.sh`, which installs the `guard.py` the
lanes need):

```bash
install -d -m 755 /opt/pythia-ops/lanes
install -m 755 /opt/pythia-src/research/ops/lanes/run_lane.sh /opt/pythia-ops/lanes/
install -m 644 /opt/pythia-src/research/ops/lanes/{lanes.py,lane.md,task_template.md} /opt/pythia-ops/lanes/
install -d -m 700 /root/pythia-lanes
echo '{"balance_usd": 40, "reserve_usd": 10, "since": "2026-10-28T00:00:00"}' > /root/pythia-lanes/budget.json
bash /opt/pythia-ops/lanes/run_lane.sh queue /path/to/task.md   # each task, from the template
bash /opt/pythia-ops/lanes/run_lane.sh run                      # one task; call it from the old runner's timer
```

It uses the research agent's secrets (`/root/pythia-agent-secrets`: `agent.env`, the deploy
key, `private-patterns.txt`), image and network; `PYTHIA_LANE_TURNS` (400), `PYTHIA_LANE_LIMIT`
(6h) and `PYTHIA_LANE_TEST_NET` may be set in `agent.env`. It replaces the runner outside the
repository (`/root/pythia-task.sh` and the script that wrote `latest.json`): stop those first,
so only one writes the lane records. Tests: `python -m pytest -q research/ops/lanes/test_lanes.py`.
