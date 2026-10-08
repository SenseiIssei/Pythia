# Operations on the VPS

Everything Pythia runs on the lab machine, and when. All times UTC.

| When | What | Where |
|---|---|---|
| always | market data recorder | container `pythia-recorder` (`research/recorder`) |
| always | headless engine: lab book, volatility model in shadow mode, `/api/lab` | container `pythia-server` on 127.0.0.1:8787 only |
| always | a second engine for autopilots, kept apart so they never touch the lab book's markets or evidence; state in `/srv/pythia-data/autopilot` | container `pythia-autopilot` on 127.0.0.1:8788 only |
| 03:30 | history backfill: 20 lab coins, every USDT pair, every USDT perp | `/etc/cron.d/pythia-backfill` |
| 04:00 | momentum paper books, engine signals, paper vs backtest review | `/etc/cron.d/pythia-paper` |
| 04:15 | sweep candidates as paper books: survivorship-free momentum, Donchian breakout (about 10 minutes, rebuilds the daily panel into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-families` |
| 04:45 | M4 shadow paper book, market-neutral on perps (`lab.paper.m4_ls`, 2 to 3 minutes, about 3 GB; rebuilds the xs_daily panel and retrains weekly into `/srv/pythia-data/lab-cache`) | `/etc/cron.d/pythia-paper-m4` |
| 05:30 | market-neutral M2 paper books (v1 and v2) | `/etc/cron.d/pythia-paper-ls` |
| 06:15 | forward report: every paper book and autopilot against its backtest (`lab.paper.forward_report`, seconds) | `/etc/cron.d/pythia-forward` |
| Sun 05:00 | volatility model retrain (published only if it passes) | `/etc/cron.d/pythia-retrain` |
| Sun 05:40 | cost calibration from the recorded books, report only | `/etc/cron.d/pythia-costs` |
| hourly :07 | health check of all of the above | `/etc/cron.d/pythia-health` |

## Health check

`system_health.sh` looks at the containers, the recorder's streams, the last
backfill, each paper book's last row, the model service and the engine's
market data (`dataHealth` in `/api/state`), and writes
`/srv/pythia-data/_health/system.json`. It never restarts anything. The Lab
page shows it ("Is everything running?"); the PC gets it with the sync.

Install or update:

```bash
scp research/ops/system_health.sh pythia-vps:/tmp/ && ssh pythia-vps 'install -m 755 /tmp/system_health.sh /opt/pythia-ops/system_health.sh'
```

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
the xs_daily pick cache, which live where those experiments ran, so their
files are exported there and copied over:

```bash
docker run --rm --memory 4g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.paper.forward_report --export-backtests
scp <exported>/forward/backtest/*.json pythia-vps:/srv/pythia-data/reports/forward/backtest/
```

Re-export after an experiment is re-run. Books without a file fall back to an
approximate band from their report (growth and volatility), marked as such.

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
