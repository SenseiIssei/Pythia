# Model zoo (W11): every model against its baseline, retrained on a schedule

**Verdict: one of the five new zoo models beats its naive baseline out of sample. M8q, the next-day return range (10/50/90 % quantiles) for the 15 Alpaca coins, has a 1.0 % lower pinball loss than "the usual spread at today's volatility" (Diebold-Mariano p 0.012, 15 of 24 quarters), almost all of it in the upper tail. It is the zoo's first champion, in shadow; no book reads it. M8 (next-day direction), M10 (regime-aware daily volatility), M11 (slippage of the demo fills) and M12 (BTC and SPY correlation regime) do not pass their gates, so nothing uses them; they are retrained on schedule and their newest candidate is scored in shadow every day.**

Run of 15 October 2026 on the local data mirror (recorder history to 14 October, the learning loop's ledger of 78 demo orders, Yahoo daily closes), with the cron entry point itself: `python -m lab.models.train --due`.

## What the zoo is

One spec per model (target, features, horizon, universe, metric, baseline, retrain schedule, who may use it), one module per model (`lab/models/m*.py`: data, fit, predict, baseline, loss, save, restore), and one machinery for all of them (`lab/models/core.py`, `train.py`):

- **Evaluation:** purged walk-forward, quarterly folds from a fixed first test date with the label horizon as embargo (M11: five expanding time blocks, one-hour embargo). Model and baseline are fitted on the same training rows and scored on the same test rows.
- **Gate:** lower mean loss than the baseline, and a Diebold-Mariano test on the per-day mean loss difference with p below 0.05 (Newey-West lag = horizon). A model that fails is kept and scored in shadow, never promoted, never used.
- **Champion and challenger:** every retrain writes a candidate under `models/registry/<name>/candidates/`; `lab.ops.registry` promotes it only if it passes its gate and, when there is a champion, is better by a margin on the rows the champion never saw. Every decision is a line in `decisions.jsonl`.
- **Shadow:** the champion (or, without one, the newest candidate, marked as such) writes down its forecast for the newest day before the outcome is known; once known, it is scored against the baseline, overall and per week.
- **Drift:** each input over the last 30 days (M12: 120) against its training deciles, with the engine's rules (outside the 0.5 to 99.5 % training range on more than 5 % of rows is drift).
- **Report:** `reports/models/latest.json` with the lab feed header (docs/LAB-FEEDS.md), read by the Models page, Home and Research. A promotion or a drifting model is posted once through `lab.ops.notify`.

M1 (next-hour vol) and M2 (weekly ranking) stay with the learning loop, which retrains them; the zoo reports on them. M7 (regime HMM) is retired and listed as a record.

## Results

| Model | Target | Metric | Model | Baseline | Better | DM p | Quarters won | Gate |
|---|---|---|---|---|---|---|---|---|
| M8 direction | P(next day up), 15 Alpaca coins | log loss | 0.6957 | 0.6937 (base rate) | -0.3 % | 0.146 | 13 of 24 | fails |
| M8q return range | 10/50/90 % quantiles of the next day's return | pinball | 0.01167 | 0.01179 (scaled empirical quantiles) | +1.0 % | 0.012 | 15 of 24 | **passes** |
| M10 regime vol | next day's realised variance, 20 coins | QLIKE | 0.2895 | 0.3142 (HAR) | +7.8 % | 0.171 | 17 of 24 | fails |
| M11 slippage | realised bps of a demo market order | MAE (bps) | 6.46 | 5.82 (engine's cost model) | -11.0 % | 0.526 | 0 of 2 blocks | fails |
| M12 correlation regime | BTC and SPY 20-day correlation, next 20 days | squared error (Fisher z) | 0.1026 | 0.0900 (last 60 days) | -13.9 % | 0.195 | 12 of 27 | fails |

Out of sample: 2021 Q1 to 2026 Q4 for M8, M8q, M10 (30,750 and 40,422 coin-days); 2020 Q1 on for M12 (1,685 days); the last 13 of 51 fills for M11.

### M8: direction does not beat the base rate

AUC 0.497, hit rate 49.8 % against 49.3 % up days, Brier 0.2513 against 0.2503. Platt scaling keeps the forecasts near 0.5 (97 % of them between 0.4 and 0.6), and where they leave it they point the wrong way: days given 0.52 on average rose 48 % of the time, days given 0.47 rose 50 %. Next-day direction on these coins is a coin flip for this model. Nothing to use.

### M8q: the return range does, mostly in the upper tail

| Quantile | Pinball (bps) | Baseline | DM p | Share of days below it | Baseline |
|---|---|---|---|---|---|
| 10 % | 87.5 | 87.7 | 0.91 | 12.1 % | 10.9 % |
| 50 % | 174.5 | 173.5 | 0.13 | 50.8 % | 51.6 % |
| 90 % | 88.1 | 92.4 | < 0.001 | 88.8 % | 90.4 % |

The band from 10 to 90 % is narrower than the baseline's (10.2 % of price against 11.2 % on average) and holds 76.7 % of next-day returns, so it is a little too narrow (the target is 80 %): read the 10 % quantile as a one-day value at risk that is breached about one day in eight, not one in ten. The gain is small and lives in the upside: the model knows when a big up day is less likely than the coin's volatility says.

**The split is post hoc, and counted.** M8q began as M8's second head, with one gate over both (direction and pinball). The first real run showed the two disagree, so they became separate models. With two heads looked at, the Bonferroni bar is p < 0.025; M8q's 0.012 clears it.

### M10: a better forecast in most quarters, not a significant one, and the regime inputs add nothing

QLIKE 7.8 % lower than HAR and better in 17 of 24 quarters, but DM p 0.17: the per-day loss differences are dominated by a few crash days (2025 Q4, the October liquidation, has a mean QLIKE of 2.07 against 2.47, ten times a normal quarter). Its second condition fails too: the same LightGBM without the five regime inputs (BTC trend, breadth, market-vol percentile, dispersion, coin trend) scores 0.2861, better than with them. Above and below BTC's 200-day mean the picture is the same (0.397 vs 0.432 HAR, 0.154 vs 0.165). M6 (vol_daily) already showed that a better daily forecast sizes worse than the 30-day mean the books use (RW30 here: 0.4445), so this was never going to feed a book directly.

### M11: 51 fills are not enough, and the cost model is not bad

The ledger holds 78 finished demo orders over three days (11 to 14 October), 51 of them market fills with a realised slippage. Realised slippage is higher than modelled (median 11.0 bps against 8.4), but the cost model's order-to-order differences (by coin and size) track it better than a ridge-shrunk median line fitted on 20 to 40 earlier fills (level 10.5 bps, small slopes), on the two blocks with enough training fills. With so few fills a tree (the first version) was out of the question; the line is the most a few dozen fills carry. The weekly retrain will try again as fills arrive; the learning loop's per-symbol cost scaling (from 30 fills per symbol) stays what the engine may use.

### M12: the persistence baseline wins

BTC-USD and SPY daily closes from Yahoo from 2014 (BTC from the recorder starts only in 2020). The correlation moved from about zero before 2020 to coupled (above 0.3 on 62 % of test days) after, and every model fitted on the history pulls towards the old level. Three runs, all counted here: ridge on the level with BTC from the recorder (2020 on, -3.7 %, DM p 0.67), the same with BTC from Yahoo as specified (-16.1 %, p 0.16), and, tried after those failed, ridge on the change from the 60-day correlation (-13.9 %, p 0.19, kept as the candidate). None comes close. As a regime label the baseline is also better (58 % of days right against 49 %). The Models page therefore shows the regime from the last 60 days: on 14 October BTC and SPY were **coupled** (60-day correlation 0.35).

## What runs every day

`/etc/cron.d/pythia-models` at 07:15 UTC, after the learning loop (research/ops/README.md): retrain what is due (M8, M8q, M10 Sundays, M11 Mondays, M12 every 28 days), shadow forecasts and scores, drift, report, posts. On this first run M8q was promoted (published as `models/m8_quantiles/20261015T1230/`), the four others rejected by their own gates; every model wrote its first shadow forecasts (15, 15, 20 and 1 rows) and all inputs were inside their trained range.

## Who may use what

| Model | Used by | Rule |
|---|---|---|
| M8q | nothing yet | A sizing or stop study may read it, pre-registered, after 90 days of shadow scores. |
| M8, M10, M11, M12 | nothing | Not until a retrain passes its gate. |
| M1 | the engine, shadow | Unchanged (learning loop). |
| M2 | picks_ls, picks_ls_v2 (paper) | Unchanged (learning loop). |

## Reproduce

```bash
cd research/lab
PYTHIA_DATA=/path/to/data python -m lab.models.train --force m8,m8q,m10,m11,m12 --no-notify
python -m pytest tests/test_model_zoo.py
```
