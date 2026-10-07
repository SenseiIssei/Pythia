# pythia-recorder

Records the market data Pythia's research needs and cannot download later:
order books, funding, open interest, liquidations and the Kraken/Binance spread.
Runs 24/7 on the VPS in Docker. Masterplan phase 3.

## What it records

| Table | Source | Cadence |
|---|---|---|
| `kraken/trades` | Kraken WS v2, every trade, 20 coins | live |
| `kraken/book20` | local book from snapshot + deltas, CRC32-checked, top 20 | every 5 s |
| `binance/book20` | Binance spot `depth20@1000ms`, top 20 | every 5 s |
| `bybit/book20` | Bybit spot `orderbook.200` (USDT pairs), local book, sequence-checked, top 20 | every 5 s |
| `okx/book20` | OKX spot `books` (USDT pairs), local book, sequence-checked, top 20 | every 5 s |
| `coinbase/book20` | Coinbase Exchange `level2_batch` (USD pairs, no TRX), full local book, top 20 | every 5 s |
| `binance_um/premium` | mark, index, funding rate, next funding | every 60 s |
| `binance_um/open_interest` | per perp | every 60 s |
| `binance_um/liquidations` | `!forceOrder@arr`, all symbols | live |
| `spread/kraken_binance` | Kraken USD vs Binance USDT through Kraken USDT/USD, both executable edges | every 15 s |

Binance trades and klines are not recorded live, because data.binance.vision
publishes them. `python -m recorder.backfill` fetches spot 1m klines (from
2020), USD-M funding (from 2020) and USD-M metrics (from 2022), checks each
archive against its published SHA-256, and skips files that already exist.

## Layout

```
/srv/pythia-data/
  <source>/<table>/date=YYYY-MM-DD/part-*.parquet   today, flushed every 2 min
  <source>/<table>/date=YYYY-MM-DD/day.parquet      finished days, compacted hourly
  hist/binance_spot/klines_1m/symbol=X/YYYY-MM.parquet
  hist/binance_um/{funding,metrics}/symbol=X/YYYY-MM.parquet
  _health/status.json                              rewritten every minute
```

All `book20` tables share one schema (`schemas.BOOK`). `symbol` is the venue's
own spelling (`BTC/USD`, `BTCUSDT`, `BTC-USDT`, `BTC-USD`); `update_id` is
Binance's `lastUpdateId`, Bybit's `u` or OKX's `seqId`, null for Kraken and
Coinbase. The three newer books feed the cost calibration
(`research/lab`, experiment `costs`), which picks up every venue that has data.

Every live row has `ts_recv_us`, the time this machine received it. Join on
that column in research, never on the exchange time alone, or a backtest sees
data before it could have arrived.

Read it with anything that speaks hive-partitioned parquet:

```python
import polars as pl
pl.scan_parquet("/srv/pythia-data/spread/kraken_binance/**/*.parquet").collect()
```

## Operating it

```bash
ssh pythia-vps
```

(`pythia-vps` is an alias in `~/.ssh/config` for the server and its user.)

```bash
cat /srv/pythia-data/_health/status.json
```

```bash
docker logs --tail 50 pythia-recorder
```

Deploy a change: copy this folder to `/opt/pythia-recorder`, then

```bash
cd /opt/pythia-recorder && docker compose up -d --build
```

The backfill runs daily at 03:30 UTC from `/etc/cron.d/pythia-backfill`
(log: `/var/log/pythia-backfill.log`).

## Guard rails

- Container capped at 1 GB RAM and one CPU; the VPS also serves the websites.
- Below 20 GB free disk the five book tables pause (`PYTHIA_MIN_FREE_GB`), the
  small tables keep going. `status.json` says so.
- Kraken's book checksum only triggers a resync once it has matched at least
  once for that symbol, so a formatting bug cannot turn into a resubscribe loop.
- Bybit, OKX and Coinbase (`recorder/books.py`) follow the same rule with the
  check each venue offers: Bybit's update id must go up by one, OKX's
  `prevSeqId` must chain to the last `seqId` (OKX's `checksum` field is 0 since
  2026; a non-zero one is checked too), and a Coinbase book, which carries
  neither, counts as broken when its best bid stays at or above its best ask
  for three messages. On top: one resubscribe per symbol per minute at most,
  and a symbol that breaks ten times in an hour stops recording until the next
  restart (logged, and counted as `<venue>_given_up` in `status.json`).
- `PYTHIA_BOOK_VENUES` (default `bybit,okx,coinbase`) switches the newer book
  feeds off one by one, for example if the one CPU is not enough. All three
  together took about 10 % of one core on a desktop.
- A venue whose symbol list cannot be loaded retries every five minutes and
  shows as stale in `status.json`; Kraken and Binance are not held up by it.

Tests (no network; the fixtures are recorded messages of each venue; needs
`pytest` next to `requirements.txt`, which the image does not install):

```bash
cd research/recorder && python -m pytest tests
```
- Binance serves USD-M market streams under `/market/ws`. The bare `/ws` path
  accepts the subscription and then stays silent.
