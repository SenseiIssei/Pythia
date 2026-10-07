# Operations on the VPS

Everything Pythia runs on the lab machine, and when. All times UTC.

| When | What | Where |
|---|---|---|
| always | market data recorder | container `pythia-recorder` (`research/recorder`) |
| always | headless engine: lab book, volatility model in shadow mode, `/api/lab` | container `pythia-server` on 127.0.0.1:8787 only |
| 03:30 | history backfill: 20 lab coins, every USDT pair, every USDT perp | `/etc/cron.d/pythia-backfill` |
| 04:00 | momentum paper books, engine signals, paper vs backtest review | `/etc/cron.d/pythia-paper` |
| 05:30 | market-neutral M2 paper books (v1 and v2) | `/etc/cron.d/pythia-paper-ls` |
| Sun 05:00 | volatility model retrain (published only if it passes) | `/etc/cron.d/pythia-retrain` |
| hourly :07 | health check of all of the above | `/etc/cron.d/pythia-health` |

## Health check

`system_health.sh` looks at the containers, the recorder's streams, the last
backfill, each paper book's last row and the model service, and writes
`/srv/pythia-data/_health/system.json`. It never restarts anything. The Lab
page shows it ("Is everything running?"); the PC gets it with the sync.

Install or update:

```bash
scp research/ops/system_health.sh pythia-vps:/tmp/ && ssh pythia-vps 'install -m 755 /tmp/system_health.sh /opt/pythia-ops/system_health.sh'
```
