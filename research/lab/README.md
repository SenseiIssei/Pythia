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
(`--refresh` rebuilds the panel, `--refit` all models, `--refit-net` only the
funding-aware round-three models); `regime` reads that
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
| `xs_daily` (M4) | Daily cross-sectional ranking, 51 features, 584 coins incl. dead ones, entry one hour after the features | Signal yes, money not proven. Rank-IC 0.148 on 3-day returns (t 47), mostly "calm, beaten-down coins beat wild, hot ones". Long-only: dead (holdout Sharpe 0.04 at 15 bps, below BTC). Long/short on perps, picked on 2022-23: holdout Sharpe 1.19 at 15 bps, 0.33 at 41 bps, 117x turnover, deflated p 0.03 over 100 variants. All 38 slower model books are positive (median 1.42 / 0.83), the best 2.67 / 2.46 (buffer 50 %), but a plain low-vol factor in the same book makes 1.87 / 1.80. Fails gate 6. (2026-10-07) |
| `xs_daily` round 3 (M4, funding-aware) | Does a label net of the funding each side pays fix the short leg? | Partly. 18 books on 3, 5 and 7-day net labels, all positive in the holdout (median 2.10 / 1.69), funding paid lower than the gross-label twin in 18 of 18, holdout Sharpe higher in 16 of 18. The family's selection-window pick (reg7n, buffer 50 %, 100 perps) makes 2.15 / 2.00 at 18x turnover against 1.87 / 1.80 for low vol in the same book, but deflated p 0.39 over 100 variants, and its 2022-23 Sharpe (1.13) loses to the gross rank3 hold-3d book (1.54). Fails gate 6. See `results/m4_funding.md`. (2026-10-07) |
| `regime` (M5) | Probability of a 15 % BTC drawdown within 30 days, as the momentum book's switch | No. Every model has AUC under 0.5 out of sample (about 57 independent windows); Brier 0.162 at best vs 0.157 for the 200-day rule. As a switch it never beats the rule: momentum book 0.71 vs 1.04. The rule works by sitting out bear markets, not by forecasting drawdowns. (2026-10-07) |
| `vol_daily` (M6) | Better daily vol forecast for sizing | Forecast partly: next day LGBM beats HAR by 9 % QLIKE (DM p 0.04), next week it loses by 6 %. Sizing: worse. The 30-day mean the books use gives the best Sharpe (momentum 1.04 vs 0.71 with LGBM, BTC 0.82 vs 0.64); faster forecasts add turnover and cut exposure right before rebounds. Keep RW30. (2026-10-07) |
| `breakout_study` | Is the Donchian 20/10 top-10 edge robust? Pre-registered, 54 more variants counted | A real family, an unproven number. All 48 grid cells (entry 10 to 55, exit N/2 and N/3, top 5 to 30) positive at 41 bps, the base's neighbours a plateau by the registered rule, but the in-sample surface is flat and the grid's median is 0.48; robust to fills up to a day late (0.82) and 80 bps (0.90). Carried by 2024 (0.46 without it) and ten trades (96 % of P&L), XRP 37 %. Deflated p 0.01 over 100 and over all 154 trials (fat tails are not the cause, the 2.5 bar is); bootstrap 90 % interval at 41 bps -0.14 to 2.15, 93 % of draws above 0. Volume confirmation adds nothing. No change recommended. See `results/breakout_study.md`. (2026-10-08) |
| `blend_study` | Do `breakout_top10` and `tsmom_top20` blended (with the BTC+ETH 55/27 breakout as an optional third sleeve, inverse vol, a book vol target), or traded less often, clear the bar? Pre-registered, 29 trials | No. No blend beats the breakout book alone at 41 bps (0 of 12 beat both legs; the in-sample pick 0.57 vs 1.08), the legs are 0.78 correlated and the vol target only adds turnover. Momentum weekly instead of daily cuts turnover from 13 to 5 a year: the pick shows 0.75 at 41 bps but that is weekday luck (other weekdays 0.36 to 0.61, seven weekday tranches 0.51, daily 0.32). Breakout needs daily checks (weekly 0.43). Deflated p 0.00 to 0.02 over 183 trials; no paper book added. See `results/blend_study.md`. (2026-10-11) |
| `etf_trend` | Weekly dual momentum and trend with vol targeting on 15 US ETFs, for the Alpaca paper account. Pre-registered, 20 trials, judged from 2017 at 5 and 10 bps against SPY and 60/40 | No. Run on Yahoo's adjusted closes from 2000 (Stooq now serves a page). The pick (trend 63d, 8 % vol target) makes Sharpe 0.68, 5.3 % a year, drawdown 17 % out of sample, against SPY 0.88 / 15.4 % / 34 % and 60/40 0.91 / 9.7 % / 21 %; behind SPY in 9 of 10 years, deflated p fails, below 60/40. No paper book. (2026-10-13) |
| `tsmom_tranches` | tsmom_top20's targets in seven weekly tranches (one rebalanced each day, 50 % band), at Alpaca-like costs | Forward evidence only. Out of sample (590 segments, delisted included, to 2026-09-30) Sharpe 0.58 at 15 bps (Alpaca maker), 0.52 at 35 bps (Alpaca taker plus slippage), 0.41 at 70 bps, against 0.53 / 0.36 / 0.07 for the daily book; drawdown 23 %, 5x turnover a year. Deflated p 0.00 over 184 trials; bootstrap 90 % band at 35 bps -0.59 to 1.52. 53 % of the exposure sits in coins Alpaca does not list. Runs as the paper book `tsmom_tranches`. See `results/tsmom_tranches.md`. (2026-10-12) |
| `fast_strategies` | Faster trades on the 15 Alpaca coins: 4h and 1h Donchian and EMA trend, short-term reversal, vol breakout with a time stop, each with and without a BTC gate, at Alpaca taker (35 bps) and maker (15 bps). Pre-registered, 81 trials | No paper book. The 4h picks are net positive at taker cost out of sample (Sharpe 0.49 to 1.11, 88 to 455 bps net per trade, 0.3 to 0.8 round trips a day), survive a late fill and the survivorship-free twin, but all lose in 2025 and deflated p is 0.00 over 265 trials (bar 2.74). 1h does not pay (0.06 to 0.65, twins negative). Trades held under 12 h earn a median 15 bps gross against 70 bps of taker round trip; the fee level allows holds of about two days or more. See `results/fast_strategies.md`. (2026-10-13) |
| `vol_managed` | Volatility-managed long exposure (min(1, TV / forecast vol), no-trade bands 10 or 25 %, optional BTC 200-day gate) on BTC, ETH and an equal-weight basket of the 15 Alpaca coins with RW30, EWMA and M1 rebuilt point in time; and as an overlay on breakout_top10 and tsmom_tranches. Pre-registered, 91 trials, Alpaca costs | No paper book. Vol management alone barely moves Sharpe (ungated RW30 medians 0.71 / 0.48 / 0.47 at 35 bps against buy and hold 0.76 / 0.42 / 0.47) but cuts drawdowns. The picks are the BTC gate plus RW30 sizing: BTC 0.81 (drawdown 20 % vs 53 %), ETH 0.85 (26 % vs 68 %), basket 0.64 (35 % vs 77 %), 0.41 to 0.60 filled a day late, basket twin 0.27. M1 reproduces (QLIKE 11.8 % below HAR) but its daily aggregate forecasts next-day RV 7 % worse than RW30 and adds 7 to 37x turnover; it loses at 35 bps. Overlays hurt both books (1.05 vs 1.11, 0.27 vs 0.52). Deflated p 0.00 over 356 trials (bar 2.60). See `results/vol_managed.md`. (2026-10-14) |
| `meta_daily` (C14) | Can a LightGBM meta-label on the daily `breakout_top10` entries (21 features known at the entry close: M2 score and rank, realised and HAR vol, breakout strength, volume surge, BTC regime, breadth, funding, liquidity), purged quarterly walk-forward from 2021-07 with a 10-day embargo, skip or size the entries profitably? Pre-registered, 10 trials | No. Out of sample the classifier ranks trades worse than chance: AUC 0.45 on 1,124 events from 2022 (90 % band 0.39 to 0.53), 0.40 on the book's own entries, Brier 0.23 vs 0.22 for the base rate. From 2024 at 35 bps (Alpaca taker plus slippage) the unfiltered book makes Sharpe 1.06, drawdown 22 %; skip below average 0.00 (skips 98 % of decisions), skip the worst quarter -0.11, size by probability 1.05 (drawdown 20 %). Every gate fails for every use, deflated p 0.00 over 275 trials. No paper book. See `results/meta_daily.md`. (2026-10-14) |
| `regime_hmm` (M7) | A Gaussian HMM regime gate (2 to 4 states, price or full features incl. breadth and funding, filtered probabilities only, monthly expanding refits) against the BTC 200-day rule and no gate, for breakout_top10, tsmom_top20, tsmom_tranches and tsmom_regime. Pre-registered, 66 trials | No. The pick (3 states, full features, switch) beats the 200-day rule in 3 of 4 books but no difference survives deflation or the bootstrap, and it hurts the best book: breakout_top10 1.02 against 1.24 with the 200-day rule. The 200-day rule stays. Deflated p over 331 trials. See `results/regime_hmm.md`. (2026-10-14) |
| `alpaca_universe` (C16) | What the books earn on what Alpaca lists: the original books, the same books with non-Alpaca coins left in cash (what the autopilot does), and the rules choosing only among the 15 Alpaca coins (top K 5 to 15). Pre-registered, 46 trials, 35 bps | No new book, but a useful answer: leaving the unlisted coins in cash is BETTER than the original books out of sample (breakout_top10 1.17 vs 1.06, tsmom_top20 0.54 vs 0.22, tsmom_tranches 0.65 vs 0.39), so the live autopilot is set up right. Choosing only among the 15 does not beat it for breakout (0.49 vs 1.17); for momentum it looks better (tranches 0.92 vs 0.65) but the bootstrap band of the difference includes 0 and deflated p is 0.01. See `results/alpaca_universe.md`. (2026-10-15) |
| `cs2` (W8) | CS2 skins: cross-market spread Skinport vs Steam net of fees, momentum or reversion, case age and drop pool events, a LightGBM forecaster of 7 and 30-day returns (bootstrap from Skinport's 90-day sales windows now, walk-forward once the hourly collector has history), a play-money portfolio and alerts. Paper only; nothing trades skins | Too early: 1 day of history (first real collection 2026-10-15: 25,143 Skinport items, 36,470 sales rows; Steam answered every request with 429, so no spread yet). No backtest exists: the bootstrap is one snapshot compared across items (7d rank IC 0.21, 30d 0.17), in-sample, and partly a measurement effect; the 7d earlier-change signal leans to reversion (-0.13, liquid -0.08) for the same reason. Cases sit 7 to 15 % under their 30-90 day average with no age effect. Paper buys need 3 % over the 10 % round trip; nothing qualified, so the play-money book holds cash. Walk-forward needs about 52 days for 7d and 75 for 30d. See `results/cs2.md` and the CS2 Skins page. (2026-10-15) |
| `factory` (W10) | Can the lab invent its own long-only daily strategies honestly? A typed grammar (momentum, Donchian, MA cross, reversal, low vol; BTC 200-day and momentum gates, vol cap, volume confirmation, coin trend; top N by liquidity, the core 20 or Alpaca's 15 with a point-in-time twin; equal or inverse vol; daily, 3-day, weekly or weekly in 7 tranches; no-trade bands), searched on 2020-08 to 2023 only, every genome a trial in a global ledger seeded with the 377 hand-study trials, six per run to the held-back window (35 and 70 bps, drawdown below BTC, one close late, twin), survivors 30 days as forward shadow books, promotion only through the hand studies' bar. First run, 300 genomes | No paper book. 95 % of genomes look good in sample (median Sharpe 1.55; the window holds 2021); the bred cluster (top-20 trend, BTC momentum gate, every 3 days) at 2.2 to 2.6 in sample makes -0.09 to 0.88 held back (median 0.19), five of six stop. One survivor, the 5 lowest-vol of the top 20 while BTC is above its 200-day and up over 28 days: 0.88 at 35 bps, 0.69 at 70, drawdown 35 % vs 53 %, but deflated p 0.00 over 677 trials (bar 2.45); it runs 30 days as a shadow book. Weekly on the server from now on. See `results/factory_first_run.md`. (2026-10-15) |
| `memecoins` (W7) | Daily rules on the six memecoins Alpaca lists (DOGE SHIB PEPE BONK WIF TRUMP) with a small risk budget: Donchian breakout, time-series momentum, rotation, attention (volume and Binance trade-count surges), hype filters; a sleeve at 40 % vol over 6 slots; each also on a survivorship-free twin of 24 Binance memecoins. Pre-registered, 50 trials, 35 bps | No paper book. The memecoins themselves lose (equal weight -11 % a year from 2024, drawdown 91 %; every one of the 24 is 43 to 99 % off its peak), but rules that sit out most of the time are positive: the pick (tsmom 28d, BTC gate) 0.67, drawdown 19 %, below BTC's 0.74. Near miss: top-1 rotation with the BTC gate 1.15 (70 bps 0.94, drawdown 27 %, positive every year, twin 1.11, late 1.06) but deflated p 0.01 over 427 trials and 52 % of its P&L from PEPE. Buying volume surges pays only in 2024; fading them loses. See `results/memecoins.md`. (2026-10-15) |
| `listings` (W6) | The listing effect: every first Binance listing since 2020 (first hour or first day, held 1, 3, 7, 30 days), the cross-venue pop (a coin on Binance newly listed on Coinbase or Kraken) and "buy the first Alpaca listing, hold N days", all net of 35 bps per side and against BTC. Pre-registered, 16 trials, month bootstrap, Holm and deflation | No. Buying a listing loses against BTC in every one of the 16 cells. 568 first Binance listings: from 2024 the best in-sample cell (first day, hold 1 day) makes -1.6 % per event vs BTC (252 events, band -4.7 % to +1.4 %), and holding longer only gets worse (first hour, 30 days: -18.7 %, hit 23 %). 306 cross-venue listings (141 Coinbase, 165 Kraken): bought the first hour after, -2.8 % at 3 days out of sample (114 events, band -4.5 % to -1.0 %), negative in 2024, 2025 and 2026. The pop is real but comes the day before, when the listing is announced (+5.3 % vs BTC for Coinbase, +1.7 % for Kraken), and cannot be traded on the listing alert. 22 Alpaca listings since its launch batch: $1,000 each would have lost $1,699 at 7 days. Holm p 1.00, deflated p 0.00 over 393 trials. No paper book; the watcher `lab.ops.listings` posts every new listing to Telegram, information only. See `results/listings.md`. (2026-10-15) |
| `equities_ranking` (M9) | Can a LightGBM LambdaRank model (momentum 1/3/6/12 and 12-1, 1-week reversal, vol 21/63, beta, 52-week high, size and volume trend from dollar volume, seven cluster-relative versions) pick S&P 500 stocks for 5, 10 or 20 days better than the index? Point-in-time members (1,185 names ever in the index, dead ones with their last prices) from a public GitHub dataset because Yahoo was not reachable; yearly purged walk-forward refits, weekly top 20 / 50, filled at the next close, 5 bps a side. Pre-registered, 45 trials incl. 16 baselines | No. The model ranks no better than chance: rank IC -0.002 to -0.014 in the 2010-15 selection window, 0.006 to 0.015 out of sample (t under 1.9 with overlapping weeks). Its pick (h10, full features, top 20) makes Sharpe 0.39 from 2016 at 32 % vol, against SPY 0.88 and equal weight 0.72; information ratio -0.04 against equal weight, 1 % of bootstrap draws above it, all six gates fail. The best M9 book out of sample (IR 0.45) stays under the 0.58 a best-of-45 noise book shows; M9 mostly loads up on volatile names. Baselines: 12-1 momentum top 50 (the baselines' pick) Sharpe 0.72, IR 0.20, deflated p 0.11; low vol has the best Sharpe (0.76 to 0.83, drawdown 29 to 33 %) but trails the index's return; 52-week high loses. No quality proxy (no fundamentals in the data). No paper book. See `results/equities_ranking.md`. (2026-10-15) |
| `model_zoo` (W11) | One framework for every model (spec, purged walk-forward against a naive baseline, DM gate, champion and challenger, daily shadow scores, drift, `python -m lab.models.train --due` as the one cron entry point), and four new models on real data: M8 next-day direction and M8q return quantiles for the 15 Alpaca coins, M10 regime-aware daily vol, M11 slippage of the demo fills, M12 BTC and SPY correlation regime from Yahoo | One of five beats its baseline: M8q, the next-day 10/50/90 % range, 1.0 % lower pinball (DM p 0.012, 15 of 24 quarters, mostly the upper tail), first champion, shadow only. M8 direction (log loss -0.3 %, AUC 0.50), M10 (QLIKE +7.8 % but DM p 0.17, regime inputs add nothing), M11 (51 fills, cost model better) and M12 (persistence better by 14 %) fail their gates and are used by nothing. See results/model_zoo.md |
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
  the pick's deflated p is 0.91; against all 100 trials it is 0.01, because
  the best of 100 noise trials would show a Sharpe of about 2.6 (its fat
  tails, kurtosis 15, barely matter: with normal returns the p is the same,
  see `results/breakout_study.md`). If anything goes to a paper forward test
  next, this is the one.
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

Lab-only paper books. The sweep candidates and M4 failed deflation and run as
forward evidence only, which their variant string says. The two sweep
candidates also write an engine signal marked `autopilot_only`: no engine runs
them on its own, but an autopilot can claim one (see "Lab books inside
autopilots" in `crates/pythia-core/src/engine/autopilot.rs`). The signal holds
what the sweep's simulator holds after the decision close, restricted to the
20 coins the engine has markets for; the others are listed in `dropped` and
stay cash there. Its evidence is the pick's row in the sweep (the
`families_summary` JSON next to the sweep caches, else
`results/families_summary.md`), deflation failure included.
`--signals-only` refreshes the signals without stepping the books, `--dry-run`
prints both and writes nothing.

| Book | Module | What | Runs (UTC) |
|---|---|---|---|
| `tsmom_top20`, `breakout_top10` | `lab.paper.families` | sweep candidates on the most liquid coins of each day; autopilot-only engine signals | 04:15 |
| `tsmom_tranches` | `lab.paper.families` | tsmom_top20's targets held by seven tranches; each run rebalances only the tranche due that day (calendar days since 2020-01-01 modulo 7) and trades the net change; the signal carries the combined weights of all seven; evidence from `results/tsmom_tranches.md` at Alpaca-like costs; autopilot-only | 04:15 |
| `m4_ls` | `lab.paper.m4_ls` | M4 rank3, long the best 10 and short the worst 10 of the 100 most liquid USDT perps, three overlapping 3-day tranches; the selection window's pick among the slower long/short books. Live Binance USD-M touch plus 5 bps taker, settled funding booked every run, model retrained weekly on all labelled history. `--dry-run` writes nothing but the cache. | 04:45 |
| `picks_ls`, `picks_ls_v2` | `lab.paper.picks_ls` | market-neutral M2 (v1 and v2) | 05:30 |

### Forward report

`lab.paper.forward_report` (06:15 UTC, see `research/ops/README.md`) asks of
every paper book and every autopilot of the autopilot engine whether the
forward result is what the backtest led us to expect, in one plain sentence
each: "on track", "below the backtest's range after N days, worth watching",
"too early to say" (under 7 days), and so on. Report:
`reports/forward/latest.{md,json}`; the Lab page shows it as "Forward test".

- **Band.** A moving-block bootstrap (5-day blocks, 4000 draws) of the
  backtest's out-of-sample daily net returns, compounded over the same
  number of days the book has run: 5 % to 95 %, median in the middle, plus
  the 95 % quantile of the worst dip inside such a stretch. The series are
  `reports/forward/backtest/<book>.json`, written by `--export-backtests`
  (momentum books from the history files, sweep candidates from the sweep's
  run caches at 15 bps, M4 from the xs_daily holdout at 15 bps with funding).
  Without one the band is log-normal from the report's growth and
  volatility, marked "approximate" (the M2 books, which have only weekly
  report rows).
- **Costs.** Summed `paper_cost_bps` against `model_cost_bps`; the M2 books
  journal the modelled 10 bps as their fill cost, so they say so instead of
  a ratio. Funding where a book has it.
- **Gate 7.** Journal days and rebalances (rows with turnover over 1 %), 30
  each; for autopilots days running and closed trades.
- **Autopilots.** From `PYTHIA_AUTOPILOT_STATE_URL` (default
  `http://127.0.0.1:8788/api/state`, `off` to skip): equity against start and
  floor, return against BTC bought and held over the same window (Binance
  1-minute opens), fees as a share of the gain before fees, trades per day
  (from one day on), and realised against modelled slippage per route from
  the orders the engine still keeps. An autopilot that runs a single lab book
  is held against that book's band.

## Strategy factory (W10)

`python -m lab.factory` (weekly on the server, see `research/ops/README.md`)
invents long-only daily strategies and holds them to the hand studies' bar.

- **Grammar** (`factory/grammar.py`). A genome is universe (top N by
  liquidity, the core 20, Alpaca's 15), signal (momentum, Donchian, MA cross,
  short-term reversal, low vol), up to three filters (BTC 200-day or
  momentum gate, vol cap, volume confirmation, coin above its own average),
  selection (best K by signal, liquidity or low vol), weights (equal or
  inverse vol, empty slots in cash or the whole book spread) and rebalance
  (daily, every 3 days, weekly, weekly in 7 tranches; no-trade band 0, 25 or
  50 %). At most 7 moving parts; each costs 0.03 of fitness.
- **Search** (`factory/search.py`). A fixed budget of new genomes per run
  (300 by default), half random on the first run and a third afterwards, the
  rest mutation and crossover of the best ever tried. It sees only 2020-08
  to 2023 at 35 bps. A fixed list is scored by the worse of the list and its
  point-in-time twin (the same number of the most liquid coins at the start
  of each year), so survivorship cannot win.
- **Ledger** (`factory/ledger.py`). Every genome ever evaluated is one trial
  in `<data>/factory/ledger.jsonl`, on top of the 377 hand-study trials (bar
  Sharpe 2.43); the deflation pool only grows. `results/factory_seed/` holds
  what was counted elsewhere (the first run was made on the PC) and every run
  merges it first.
- **Gates** (`factory/evaluate.py`). Six genomes per run (best fitness, both
  in-sample halves positive, mutually uncorrelated) see 2024 onwards: Sharpe
  above 0 at 35 bps and at 70 bps, drawdown below BTC's, still positive when
  filled a close late, and for a fixed list its twin positive too. A survivor
  runs 30 days as a forward shadow book (`factory/shadow.py`, at most 6 at a
  time, 2 new per run). After 30 shadow days it is promoted only if every
  gate holds again, deflated p is above 0.95 over the whole pool and the
  forward month is not below the backtest's 5 % quantile; it then becomes a
  paper book (`factory_<key>`) stepped by `lab.paper.families` with live
  quotes. Nothing the factory does can reach live trading.
- **Report.** `reports/factory/latest.{md,json}` (JSON with the common header:
  title, updatedMs, status, headline, items) and, with `--notify`, a digest
  to Telegram or the webhook through `lab.ops.notify.post`.

Tests: `python -m pytest tests` from `research/lab`.
