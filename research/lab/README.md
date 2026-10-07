# pythia-lab

Research for Pythia: where a model or strategy has to prove itself before it
gets near the engine. Runs on the VPS next to the data the recorder writes.
Masterplan phases 4 and 6.

## Run an experiment

```bash
ssh pythia-vps
```

```bash
docker run --rm --cpus 4 --memory 8g -v /srv/pythia-data:/data -v /opt/pythia-lab:/app pythia-lab python -m lab.experiments.vol
```

The image holds only the dependencies; the code is bind-mounted from
`/opt/pythia-lab`, so a change is a copy, not a rebuild. Reports land in
`/srv/pythia-data/reports/<name>/` as dated markdown and JSON plus `latest.*`,
and reach the PC with the next sync.

On the PC, against the synced mirror (which must not be written into), point
the reports elsewhere and copy the markdown into the repo:

```bash
PYTHIA_DATA=F:/PythiaData PYTHIA_REPORTS=F:/PythiaData/agent-models/reports PYTHIA_RESULTS=results F:/PythiaData/venv-net/Scripts/python.exe -m lab.experiments.xs_daily
```

`results/<name>.md` holds the latest report of each experiment run that way.
`xs_daily` caches its panel and scores under `$PYTHIA_REPORTS/_cache`
(`--refresh` rebuilds the panel, `--refit` the models); `regime` reads that
panel for its breadth features, so run `xs_daily` first.

## The rules every experiment follows

- **Out of sample or it did not happen.** Walk-forward by quarter with an
  embargo (`cv.py`); labels that span a split are purged.
- **Costs are in every number.** A backtest without costs is not reported.
- **Count the tries.** Every variant tried goes into the deflated Sharpe
  (`metrics.py`); picking the best of many is how noise becomes a strategy.
- **Beat a baseline, not zero.** Naive and HAR for volatility, the coin
  basket and BTC for strategies, random entries for signals.
- **Write down failures.** A dead idea with a number is a result.

## Results so far

| Experiment | What it asks | Answer (2026-10-06) |
|---|---|---|
| `spread` | Does the Kraken/Binance spread ever clear fees? | No. Edge p99 2 to 9 bps against about 50 bps of fees. Logger keeps running to 30 days. |
| `vol` | Can a model forecast next-hour volatility better than HAR? | Yes. 24 of 24 quarters, 20 of 20 coins, 11.8 % lower QLIKE. ONNX in `models/vol_1h/`. |
| `meta` | Can a meta-label rescue an hourly breakout? | No. AUC 0.52, still negative after costs. |
| `tsmom` | Long-only time-series momentum, vol-scaled | Candidate. OOS Sharpe 0.72, drawdown 25 % vs 73 % for the basket. Deflated p 0.82. |
| `momentum2` | Same with a 200-day BTC regime filter, plus rotation | Regime: OOS Sharpe 1.05, drawdown 19 %, deflated p 0.86 over 50 variants. Rotation weaker. |
| `carry` | Spot long, perp short, collect funding | No. 1.4 % a year on capital from 2024, an upper bound. Perpetuals are not built. |
| `xs_daily` (M4) | Daily cross-sectional ranking, 51 features, 584 coins incl. dead ones, entry one hour after the features | Signal yes, money not proven. Rank-IC 0.148 on 3-day returns (t 47), mostly "calm, beaten-down coins beat wild, hot ones". Long-only: dead (holdout Sharpe 0.04 at 15 bps, below BTC). Long/short on perps, picked on 2022-23: holdout Sharpe 1.19 at 15 bps, 0.33 at 41 bps, 117x turnover, deflated p 0.06 over 82 variants. All 38 slower model books are positive (median 1.42 / 0.83), the best 2.67 / 2.46 (buffer 50 %), but a plain low-vol factor in the same book makes 1.87 / 1.80. Fails gate 6. (2026-10-07) |
| `regime` (M5) | Probability of a 15 % BTC drawdown within 30 days, as the momentum book's switch | No. Every model has AUC under 0.5 out of sample (about 57 independent windows); Brier 0.162 at best vs 0.157 for the 200-day rule. As a switch it never beats the rule: momentum book 0.71 vs 1.04. The rule works by sitting out bear markets, not by forecasting drawdowns. (2026-10-07) |
| `vol_daily` (M6) | Better daily vol forecast for sizing | Forecast partly: next day LGBM beats HAR by 9 % QLIKE (DM p 0.04), next week it loses by 6 %. Sizing: worse. The 30-day mean the books use gives the best Sharpe (momentum 1.04 vs 0.71 with LGBM, BTC 0.82 vs 0.64); faster forecasts add turnover and cut exposure right before rebounds. Keep RW30. (2026-10-07) |
| `costs` | What does crossing the book really cost, per coin? | Spreads are far tighter than the guesses: BTC one tick on both venues, most coins under 2 bps a side. Fees are nearly all of it: a Kraken taker round trip is 80 bps, Binance 20. Weekly, report only (2026-10-07). |

## Paper forward tests (gate 7)

`lab.paper.tsmom` runs both momentum books at 04:00 UTC from
`/etc/cron.d/pythia-paper`, with the backtest's own weight function, live
Binance prices and touch-plus-fee fills. Journals:
`/srv/pythia-data/paper/<book>/journal.csv`. 30 days and 30 rebalances are
the minimum before anything moves toward real money.
