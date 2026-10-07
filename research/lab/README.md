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

## Strategy-family sweep (2026-10-07)

`python -m lab.experiments.families` (add `--fresh` to recompute; one family:
`python -m lab.experiments.fam_<name>`). Nine families, **100 variants**, all
on one survivorship-free daily panel: every USDT pair Binance ever listed, 591
coin segments, delisted coins included, reused tickers split as in `picks.py`.
Shared code in `experiments/fam_common.py`; caches and JSON under
`<data>/agent-strategies/`; reports in `results/` (`families_summary.md` and
one `family_<name>.md` each). Pick = best in-sample (2020-08 to 2023) Sharpe at
15 bps per sub-family; judged from 2024-01-01 (1010 days) at 15 and 41 bps per
unit of turnover; deflated over all 100 variants. Pass = deflated p > 0.95,
Sharpe > 0 at 41 bps, drawdown below the benchmark.

Benchmarks out of sample: BTC Sharpe 0.78, drawdown 53 %; equal-weight
universe Sharpe -0.34, drawdown 91 %. The best of 100 noise strategies would
show an annual Sharpe of about 2.6 here, so that is roughly the bar.

| Family | In-sample pick | OOS Sharpe 15 / 41 bps | CAGR at 41 bps | Max DD at 41 bps | Turnover / yr | Sharpe BTC above / below 200d | Deflated p | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 reversal, long-only | 3d losers, all eligible | -0.91 / -1.56 | -78 % | 99 % | 193 | -0.83 / -1.06 | 0.00 | Fails. Crypto continues at 1 to 7 days, it does not revert. |
| 1 reversal, market-neutral | 7d losers vs winners | -1.18 / -2.07 | -40 % | 78 % | 83 | -1.12 / -1.26 | 0.00 | Fails. |
| 2 tsmom, survivorship-free (+ vol management) | 28d, top 20 by volume, regime, unscaled | 0.54 / 0.32 | 4 % | 24 % | 13 | 0.70 / -2.29 | 0.00 | Fails. Book-level vol scaling made every variant worse. |
| 3 Donchian breakout, BTC+ETH | 55/27, regime | 1.07 / 1.03 | 27 % | 28 % | 4 | 1.38 / -0.96 | 0.01 | Fails deflation only. All 12 variants positive at 41 bps. |
| 3 Donchian breakout, top 10 | 20/10, no regime | 1.20 / 1.08 | 22 % | 22 % | 9 | 1.78 / -0.55 | 0.01 | Fails deflation only. Strongest robust family. |
| 4 pair spreads | 90d window, z 1.5, cointegrated only | -1.21 / -1.66 | -5 % | 12 % | 5 | -1.62 / -0.37 | 0.00 | Fails. 8 % of windows test cointegrated (5 % by chance), and it does not carry into the next window. |
| 5 seasonality, BTC | 2 best weekdays | -0.32 / -1.30 | -33 % | 70 % | 104 | -0.43 / -0.16 | 0.00 | Fails. 1 of 66 calendar effects survives BH, and it vanishes out of sample. |
| 5 seasonality, ETH | turn of month | -0.86 / -1.10 | -27 % | 63 % | 24 | -0.96 / -0.69 | 0.00 | Fails. |
| 6 funding timing, BTC+ETH | contrarian, z 90d | 0.08 / -0.17 | -4 % | 23 % | 15 | -0.56 / 0.69 | 0.00 | Fails. |
| 6 funding timing, top 20 | trend, z 180d | 0.64 / 0.42 | 4 % | 16 % | 8 | 1.16 / -1.05 | 0.00 | Fails. |
| 6 open interest (old 20 coins, from 2022) | OI and price up, 7d | 0.69 / 0.13 | 1 % | 36 % | 38 | 1.14 / -0.38 | 0.00 | Fails. |
| 7 low vol, long-only | lowest-vol quintile of top 100 | 0.28 / 0.23 | -5 % | 75 % | 12 | 0.35 / 0.14 | 0.00 | Fails. Low-beta ranking is worse (-1.2 to -1.5). |
| 7 low vol, market-neutral (perps) | vol 60d, top 50, beta-neutral | 2.11 / 1.91 | 72 % | 17 % | 23 | 2.38 / 1.78 | 0.21 | Fails deflation. In-sample 0.54: an altcoin-bleed bet that the out-of-sample years favoured; shorts pay heavy funding. |
| 8 dual momentum | top 10 by 28d, regime | 0.07 / -0.05 | -2 % | 31 % | 8 | 0.07 / 0.11 | 0.00 | Fails. |
| 8 trend + carry | tsmom top 20 minus crowded funding, regime | 0.71 / 0.37 | 3 % | 17 % | 14 | 0.93 / -2.24 | 0.00 | Fails. |
| 8 XS momentum long/short | 28d quintiles, top 50 | -0.63 / -1.01 | -32 % | 68 % | 49 | 0.59 / -2.48 | 0.00 | Fails. M2's ranking skill is not plain momentum. |
| 9 risk-parity ensemble, spot | 10 spot picks with IS Sharpe > 0.5 | 0.42 / 0.11 | 1 % | 23 % | 15 | 0.69 / -0.50 | 0.00 | Fails. |
| 9 risk-parity ensemble, all | all 16 picks | 0.30 / -0.35 | -3 % | 15 % | 17 | 0.58 / -0.71 | 0.00 | Fails. |

**Nothing passes.** Three findings matter beyond the verdict:

- The existing paper candidate leans on survivorship. Through the same
  simulator it makes OOS Sharpe 1.07 on today's 20 coins, but the identical
  rule on the 20 most liquid coins of each day makes 0.54 (0.32 at 41 bps).
  Against this sweep's bar its deflated p is 0.00 (0.22 with the pure-noise
  variance 1/T).
- Breakouts are the most robust family: every variant positive out of sample
  at 41 bps, low turnover, drawdown under half of BTC's. Inside its own family
  the pick's deflated p is 0.91; against all 100 trials it is 0.01, mostly
  because its daily returns are fat-tailed (kurtosis 15). If anything goes to
  a paper forward test next, this is the one.
- The low-vol market-neutral book has the highest out-of-sample Sharpe (2.1)
  but its in-sample Sharpe was 0.5 and its money comes from shorting
  high-volatility coins in an altcoin bear market (see `family_lowvol.md`).
  It needs perpetuals, which Pythia does not trade.

Deflation sensitivity for every pick (raw variance, pure-noise variance,
within-family only) is in `families_summary.md`.

## Paper forward tests (gate 7)

`lab.paper.tsmom` runs both momentum books at 04:00 UTC from
`/etc/cron.d/pythia-paper`, with the backtest's own weight function, live
Binance prices and touch-plus-fee fills. Journals:
`/srv/pythia-data/paper/<book>/journal.csv`. 30 days and 30 rebalances are
the minimum before anything moves toward real money.
